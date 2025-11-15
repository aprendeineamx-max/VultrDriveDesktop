from __future__ import annotations

import datetime as _dt
from typing import Dict, Optional


class StorageSessionManager:
    """
    Coordina la validaciA3n de sesiones (S3 y MEGA) y el auto-montaje.
    Mantiene un diccionario con el A?ltimo estado calculado para la UI.
    """

    def __init__(self, config_manager, rclone_manager, logger=None):
        self.config_manager = config_manager
        self.rclone_manager = rclone_manager
        self.logger = logger
        self.profile_states: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

    def ensure_profiles_ready(self, auto_mount: bool = True) -> Dict[str, Dict]:
        """
        Verifica todos los perfiles configurados. Si la sesiA3n requiere refresh,
        ejecuta el proceso de relogueo y opcionalmente monta la unidad.
        Retorna el estado actualizado de todos los perfiles.
        """
        states = {}
        for profile_name in self.config_manager.list_profiles():
            try:
                states[profile_name] = self._ensure_profile(profile_name, auto_mount=auto_mount)
            except Exception as exc:  # pragma: no cover - queremos seguir con los demA?s perfiles
                if self.logger:
                    self.logger.error("Error verificando perfil %s: %s", profile_name, exc, exc_info=True)
                states[profile_name] = {
                    'profile': profile_name,
                    'type': 'unknown',
                    'status': 'error',
                    'last_error': str(exc),
                    'days_active': None,
                    'next_refresh_ts': None,
                    'auto_mount_letter': None,
                    'auto_mount': False,
                    'mount_status': {'status': 'error', 'message': str(exc)},
                }
        self.profile_states = states
        return states

    def get_states(self) -> Dict[str, Dict]:
        return self.profile_states

    # ------------------------------------------------------------------
    # LA3gica interna
    # ------------------------------------------------------------------

    def _ensure_profile(self, profile_name: str, auto_mount: bool) -> Dict:
        profile = self.config_manager.get_config(profile_name) or {}
        profile_type = profile.get('type', 's3').lower()
        refresh_days = self.config_manager.get_profile_refresh_interval(profile_name)
        session = self.config_manager.get_profile_session(profile_name)

        now = _dt.datetime.utcnow()
        last_login_ts = session.get('last_login_ts')
        days_active = self._days_since(last_login_ts, now)
        last_status = session.get('last_status') or 'unknown'

        needs_refresh = not last_login_ts or last_status != 'ok'
        if not needs_refresh and days_active is not None and refresh_days:
            needs_refresh = days_active >= refresh_days

        if self.logger:
            self.logger.debug("Perfil %s (%s) - last_login=%s days=%.2f refresh=%s",
                              profile_name, profile_type, last_login_ts, days_active or 0, needs_refresh)

        refresh_success = True
        refresh_message = None
        if needs_refresh:
            refresh_success, refresh_message = self.refresh_profile_session(profile_name, profile)

        profile_auto_mount = profile.get('auto_mount', True)
        mount_status = {'status': 'skipped', 'message': 'Auto-mount deshabilitado'}
        if refresh_success and auto_mount and profile_auto_mount:
            mount_status = self._auto_mount(profile_name, profile_type, profile)

        updated_session = self.config_manager.get_profile_session(profile_name)
        updated_login_ts = updated_session.get('last_login_ts')
        updated_days_active = self._days_since(updated_login_ts, now)
        next_refresh_ts = None
        if refresh_days and updated_login_ts:
            try:
                login_dt = _dt.datetime.fromisoformat(updated_login_ts)
                next_refresh_ts = (login_dt + _dt.timedelta(days=refresh_days)).isoformat()
            except ValueError:
                pass

        state = {
            'profile': profile_name,
            'type': profile_type,
            'status': 'ok' if refresh_success else 'error',
            'last_error': None if refresh_success else refresh_message,
            'last_login_ts': updated_login_ts,
            'days_active': updated_days_active,
            'refresh_interval_days': refresh_days,
            'next_refresh_ts': next_refresh_ts,
            'auto_mount_letter': profile.get('auto_mount_letter'),
            'auto_mount': profile.get('auto_mount', True),
            'mount_status': mount_status,
        }
        return state

    def refresh_profile_session(self, profile_name: str, profile: Optional[Dict] = None) -> (bool, Optional[str]):
        """
        Ejecuta un comando ligero de rclone para validar las credenciales.
        Si falla, se registra el error en la sesiA3n.
        """
        profile = profile or (self.config_manager.get_config(profile_name) or {})
        section = self.rclone_manager.create_rclone_config(profile_name)
        if not section:
            message = f"No existe configuraciA3n para el perfil '{profile_name}'."
            self.config_manager.update_profile_session(
                profile_name,
                last_check_ts=_dt.datetime.utcnow().isoformat(),
                last_status='error',
                last_error=message,
            )
            return False, message

        cmd = ['lsd', f'{section}:']
        result = self.rclone_manager.run_rclone_command(cmd, timeout=30)
        now_iso = _dt.datetime.utcnow().isoformat()
        if result.returncode == 0:
            self.config_manager.update_profile_session(
                profile_name,
                last_login_ts=now_iso,
                last_check_ts=now_iso,
                last_status='ok',
                last_error=None,
            )
            if self.logger:
                self.logger.info("Perfil %s validado correctamente.", profile_name)
            return True, result.stdout.strip()

        error_msg = result.stderr.strip() or result.stdout.strip() or "Error desconocido al validar credenciales."
        self.config_manager.update_profile_session(
            profile_name,
            last_check_ts=now_iso,
            last_status='error',
            last_error=error_msg,
        )
        if self.logger:
            self.logger.error("Perfil %s fallA3 en validaciA3n: %s", profile_name, error_msg)
        return False, error_msg

    def _auto_mount(self, profile_name: str, profile_type: str, profile: Dict) -> Dict:
        letter = (profile.get('auto_mount_letter') or '').upper()
        if not letter:
            return {'status': 'skipped', 'message': 'Sin letra configurada'}

        bucket = profile.get('default_bucket') if profile_type == 's3' else ''
        success, message, _process = self.rclone_manager.mount_drive(profile_name, letter, bucket)

        if success:
            now_iso = _dt.datetime.utcnow().isoformat()
            self.config_manager.update_profile_session(
                profile_name,
                last_mount_letter=letter,
                last_mount_ts=now_iso,
            )
            if self.logger:
                self.logger.info("Perfil %s montado automaticamente en %s", profile_name, letter)
            return {'status': 'mounted', 'message': message}

        if self.logger:
            self.logger.warning("Auto-mount fallA3 para %s: %s", profile_name, message)
        return {'status': 'error', 'message': message}

    @staticmethod
    def _days_since(timestamp: Optional[str], now: Optional[_dt.datetime] = None) -> Optional[float]:
        if not timestamp:
            return None
        try:
            dt_value = _dt.datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        now = now or _dt.datetime.utcnow()
        delta = now - dt_value
        return round(delta.total_seconds() / 86400, 2)
