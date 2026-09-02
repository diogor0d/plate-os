"""Cookie-session Web Push management contracts."""

import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address, ip_address

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def _is_public_address(value: str | IPv4Address | IPv6Address) -> bool:
    address = ip_address(value)
    return address.is_global and not any(
        (
            address.is_loopback,
            address.is_private,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _validate_endpoint_shape(value: HttpUrl) -> HttpUrl:
    host = value.host
    if (
        value.scheme != "https"
        or value.username is not None
        or value.password is not None
        or value.port != 443
        or host is None
    ):
        raise ValueError("push endpoint must be an HTTPS URL on port 443 without userinfo")

    normalized_host = host.rstrip(".").lower()
    try:
        address = ip_address(normalized_host.strip("[]"))
    except ValueError:
        labels = normalized_host.split(".")
        if len(labels) < 2 or any(not label for label in labels):
            raise ValueError("push endpoint must use a public DNS name")
        if labels[-1] in {
            "corp",
            "home",
            "internal",
            "intranet",
            "lan",
            "local",
            "localdomain",
            "localhost",
            "onion",
        } or normalized_host.endswith(".home.arpa"):
            raise ValueError("push endpoint must use a public DNS name")
    else:
        if not _is_public_address(address):
            raise ValueError("push endpoint must use a public IP address")
    return value


class PushConfigOut(BaseModel):
    enabled: bool
    application_server_key: str | None
    subscriptions: list["PushSubscriptionOut"] = Field(default_factory=list)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=256)
    auth: str = Field(min_length=1, max_length=128)


class PushSubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    endpoint: HttpUrl
    expiration_time: int | None = None
    keys: PushKeys
    device_name: str | None = Field(default=None, max_length=80)

    _endpoint_is_public_https = field_validator("endpoint")(_validate_endpoint_shape)


class PushSubscriptionOut(BaseModel):
    id: uuid.UUID
    device_name: str | None
    created_at: datetime
    updated_at: datetime
    last_success_at: datetime | None
    enabled: bool


class PushSubscriptionDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: HttpUrl

    _endpoint_is_public_https = field_validator("endpoint")(_validate_endpoint_shape)
