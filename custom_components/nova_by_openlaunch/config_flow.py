"""Config flow for NOVA by Open Launch integration."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import Any

import voluptuous as vol
import websockets

from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_NAME

from .const import (
    DEFAULT_PORT,
    DOMAIN,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_SERIAL,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_host(host: str) -> str:
    """Bracket raw IPv6 literals so they're safe in ws://host:port URIs."""
    try:
        if isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address):
            return f"[{host}]"
    except ValueError:
        pass
    return host


class NovaByOpenLaunchConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NOVA by Open Launch."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_host: str | None = None
        self._discovered_port: int | None = None
        self._discovered_name: str | None = None
        self._discovered_manufacturer: str | None = None
        self._discovered_model: str | None = None
        self._discovered_serial: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step (manual configuration)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = _normalize_host(user_input[CONF_HOST])
            port = user_input[CONF_PORT]

            if await self._test_connection(host, port):
                unique_id = f"{host}:{port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_MANUFACTURER: "Open Launch",
                        CONF_MODEL: "NOVA",
                    },
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="NOVA by Open Launch"): str,
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle Zeroconf/mDNS discovery."""
        _LOGGER.debug("Zeroconf discovery: %s", discovery_info)

        props = discovery_info.properties

        self._discovered_host = _normalize_host(str(discovery_info.host))
        self._discovered_port = discovery_info.port or DEFAULT_PORT

        # Device info from mDNS TXT records
        self._discovered_manufacturer = props.get("manufacturer", "Open Launch")
        self._discovered_model = props.get("model", "NOVA")
        self._discovered_serial = props.get("serial")

        self._discovered_name = discovery_info.name.removesuffix(
            f".{discovery_info.type}"
        ) or "NOVA by Open Launch"

        if not self._discovered_host:
            return self.async_abort(reason="no_host")

        # Use serial as unique ID — hardware-stable across network changes
        unique_id = self._discovered_serial or f"{self._discovered_host}:{self._discovered_port}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(
            updates={
                CONF_HOST: self._discovered_host,
                CONF_PORT: self._discovered_port,
            }
        )

        # Show confirmation dialog
        self.context["title_placeholders"] = {"name": self._discovered_name}

        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user confirmation of Zeroconf discovered device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if await self._test_connection(
                self._discovered_host, self._discovered_port
            ):
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, self._discovered_name),
                    data={
                        CONF_NAME: user_input.get(CONF_NAME, self._discovered_name),
                        CONF_HOST: self._discovered_host,
                        CONF_PORT: self._discovered_port,
                        CONF_MANUFACTURER: self._discovered_manufacturer,
                        CONF_MODEL: self._discovered_model,
                        CONF_SERIAL: self._discovered_serial,
                    },
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self._discovered_name
                    ): str,
                }
            ),
            description_placeholders={
                "host": self._discovered_host,
                "port": str(self._discovered_port),
                "model": self._discovered_model,
                "manufacturer": self._discovered_manufacturer,
            },
            errors=errors,
        )

    async def _test_connection(self, host: str, port: int) -> bool:
        """Test if we can connect to the device via WebSocket."""
        uri = f"ws://{host}:{port}"
        try:
            websocket = await asyncio.wait_for(
                websockets.connect(uri),
                timeout=10.0,
            )
            await websocket.close()
            return True
        except (OSError, asyncio.TimeoutError, ConnectionRefusedError) as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return False
