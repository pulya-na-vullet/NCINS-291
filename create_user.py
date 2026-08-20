#!/usr/bin/env python3
"""Создание и дозаполнение тестового пользователя AD для NCINS-291.

Данные в JWT Keycloak (realm users, client ufr-eos-ul-ncins) приходят
из тестового Active Directory msk.ad2012.loc. Поэтому пользователя нужно
создавать/править в AD, а не в самом Keycloak.

Примеры:
  python create_user.py create --username adNcinsSfa --password 'Pe1fCLpx2hJc!'
  python create_user.py fill --username adNcins
  python create_user.py csv --username adNcinsSfa --password 'Pe1fCLpx2hJc!'
  python create_user.py verify --username adNcins --password 'pe1fCLpx2hJc'
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import ssl
import sys
from pathlib import Path
from typing import Any

try:
    from ldap3 import ALL, Connection, MODIFY_REPLACE, NTLM, Server, Tls
    from ldap3.core.exceptions import LDAPException
except ImportError:  # pragma: no cover - optional until pip install
    ALL = Connection = MODIFY_REPLACE = NTLM = Server = Tls = None  # type: ignore
    LDAPException = Exception  # type: ignore

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore


DOMAIN = "msk.ad2012.loc"
BASE_DN = "DC=msk,DC=ad2012,DC=loc"
USER_OU = "OU=Users,OU=Techusers,OU=PROJECTS,DC=msk,DC=ad2012,DC=loc"
GROUP_OU = "OU=Groups,OU=Techusers,OU=PROJECTS,DC=msk,DC=ad2012,DC=loc"
DEFAULT_LDAP_HOST = os.environ.get("AD_LDAP_HOST", DOMAIN)
DEFAULT_LDAP_PORT = int(os.environ.get("AD_LDAP_PORT", "636"))

KEYCLOAK_TOKEN_URL = os.environ.get(
    "KEYCLOAK_TOKEN_URL",
    "https://idp-test.alfaintra.net/auth/realms/users/protocol/openid-connect/token",
)
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "ufr-eos-ul-ncins")
KEYCLOAK_SCOPE = os.environ.get(
    "KEYCLOAK_SCOPE",
    "openid ufr-eos-ul-ncins-attributes profile groups-include-all email",
)

# Логин/пароль из тикета NCINS-291. Пароль можно переопределить через env.
TICKET_USERNAME = "adNcins"
TICKET_PASSWORD = os.environ.get("ADNCINS_PASSWORD", "pe1fCLpx2hJc")
TEMPLATE_USERNAME = "u_m1n2y"

# Атрибуты AD, которые эталонный пользователь отдаёт в JWT.
# Имена кастомных полей совпадают с порталом (alfamiiseq*) и с JWT (alfaMiisEq*).
REQUIRED_AD_ATTRIBUTES = (
    "givenName",
    "sn",
    "middleName",
    "displayName",
    "mail",
    "title",
    "department",
    "alfaMiisEqNumber",
    "alfaMiisEqMnemonic",
    "alfaMiisEqProfile",
)

REQUIRED_JWT_CLAIMS = (
    "sAMAccountName",
    "preferred_username",
    "email",
    "given_name",
    "family_name",
    "middle_name",
    "name",
    "displayName",
    "title",
    "department",
    "alfaMiisEqNumber",
    "alfaMiisEqMnemonic",
    "alfaMiisEqProfile",
)

# Значения эталона u_m1n2y. Для fill существующего adNcins ФИО/почту
# можно оставить своими — важнее, чтобы ключи атрибутов были заполнены.
TEMPLATE_VALUES: dict[str, str] = {
    "givenName": "Михаил",
    "sn": "Леканов",
    "middleName": "Васильевич",
    "displayName": "Леканов Михаил Васильевич",
    "mail": "lekanov@alfabank.ru",
    "title": "Должность",
    "department": "Развития оффлайн каналов",
    "alfaMiisEqNumber": "9999",
    "alfaMiisEqMnemonic": "MAA6",
    "alfaMiisEqProfile": "1111",
}

CSV_FIELDNAMES = (
    "name",
    "password",
    "memberof",
    "givenName",
    "sn",
    "middleName",
    "displayName",
    "mail",
    "title",
    "department",
    "alfaMiisEqNumber",
    "alfaMiisEqMnemonic",
    "alfaMiisEqProfile",
)

MAX_SAMACCOUNTNAME_LEN = 20
UAC_NORMAL_ACCOUNT = 512
UAC_ACCOUNTDISABLE = 514


class UserScriptError(RuntimeError):
    """Ошибка сценария создания пользователя."""


def validate_username(username: str) -> str:
    username = username.strip()
    if not username:
        raise UserScriptError("Имя пользователя не задано")
    if len(username) > MAX_SAMACCOUNTNAME_LEN:
        raise UserScriptError(
            f"sAMAccountName длиннее {MAX_SAMACCOUNTNAME_LEN} символов: {username!r}"
        )
    if any(ch in username for ch in r'\/:*?"<>|'):
        raise UserScriptError(f"Недопустимые символы в имени пользователя: {username!r}")
    return username


def validate_password(password: str) -> str:
    if not password:
        raise UserScriptError("Пароль не задан")
    if ";" in password:
        raise UserScriptError(
            "Пароль не должен содержать ';' — ограничение шаблона импорта портала AD"
        )
    if len(password) < 8:
        raise UserScriptError("Пароль короче 8 символов, не пройдёт парольную политику AD")
    classes = sum(
        (
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        )
    )
    if classes < 3:
        raise UserScriptError(
            "Пароль должен содержать минимум 3 класса символов "
            "(строчные, заглавные, цифры, спецсимволы)"
        )
    return password


def user_dn(username: str, ou: str = USER_OU) -> str:
    return f"CN={username},{ou}"


def attributes_for_create(username: str, extra: dict[str, str] | None = None) -> dict[str, Any]:
    values = dict(TEMPLATE_VALUES)
    if extra:
        values.update({k: v for k, v in extra.items() if v is not None})
    return {
        "objectClass": ["top", "person", "organizationalPerson", "user"],
        "cn": username,
        "sAMAccountName": username,
        "userPrincipalName": f"{username}@{DOMAIN}",
        "userAccountControl": UAC_ACCOUNTDISABLE,
        **values,
    }


def csv_row(username: str, password: str, memberof: str = "") -> dict[str, str]:
    row = {
        "name": username,
        "password": password,
        "memberof": memberof,
        **TEMPLATE_VALUES,
    }
    return {key: row.get(key, "") for key in CSV_FIELDNAMES}


def write_users_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    if len(rows) > 30:
        raise UserScriptError("Портал принимает не больше 30 учёток за один импорт")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    return path


def missing_claims(token: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for claim in REQUIRED_JWT_CLAIMS:
        value = token.get(claim)
        if value is None or value == "" or value == []:
            missing.append(claim)
    return missing


def _require_ldap() -> None:
    if Server is None or Connection is None:
        raise UserScriptError("Нужен пакет ldap3: pip install -r requirements.txt")


def _require_requests() -> None:
    if requests is None:
        raise UserScriptError("Нужен пакет requests: pip install -r requirements.txt")


def ldap_connect(
    host: str,
    port: int,
    bind_user: str,
    bind_password: str,
    use_ssl: bool = True,
    start_tls: bool = False,
) -> Connection:
    _require_ldap()
    tls = Tls(validate=ssl.CERT_NONE, version=ssl.PROTOCOL_TLS_CLIENT)
    server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL, tls=tls)
    auth = NTLM if "\\" in bind_user else None
    conn = Connection(
        server,
        user=bind_user,
        password=bind_password,
        authentication=auth,
        auto_bind=False,
        raise_exceptions=True,
    )
    if start_tls:
        conn.open()
        conn.start_tls()
        conn.bind()
    else:
        conn.bind()
    return conn


def search_user(conn: Connection, username: str, attributes: list[str] | str = "*") -> dict[str, Any] | None:
    conn.search(
        search_base=BASE_DN,
        search_filter=f"(sAMAccountName={username})",
        attributes=attributes,
    )
    if not conn.entries:
        return None
    return json.loads(conn.entries[0].entry_to_json())


def set_ad_password(conn: Connection, dn: str, password: str) -> None:
    quoted = f'"{password}"'.encode("utf-16-le")
    conn.modify(dn, {"unicodePwd": [(MODIFY_REPLACE, [quoted])]})


def create_ad_user(
    conn: Connection,
    username: str,
    password: str,
    ou: str = USER_OU,
    extra_attrs: dict[str, str] | None = None,
    group_dns: list[str] | None = None,
) -> str:
    username = validate_username(username)
    password = validate_password(password)
    if search_user(conn, username, attributes=["distinguishedName"]):
        raise UserScriptError(f"Пользователь {username} уже существует в AD")

    dn = user_dn(username, ou)
    attrs = attributes_for_create(username, extra_attrs)
    if not conn.add(dn, attributes=attrs):
        raise UserScriptError(f"Не удалось создать {dn}: {conn.result}")

    try:
        set_ad_password(conn, dn, password)
        conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [UAC_NORMAL_ACCOUNT])]})
        for group_dn in group_dns or []:
            conn.extend.microsoft.add_members_to_groups([dn], [group_dn])
    except LDAPException as exc:
        raise UserScriptError(
            f"Учётка {dn} создана, но не активирована ({exc}). "
            "Проверьте парольную политику и права bind-учётки."
        ) from exc
    return dn


def fill_ad_user(
    conn: Connection,
    username: str,
    values: dict[str, str] | None = None,
    keep_identity: bool = True,
) -> str:
    username = validate_username(username)
    found = search_user(conn, username, attributes=["distinguishedName", *REQUIRED_AD_ATTRIBUTES])
    if not found:
        raise UserScriptError(f"Пользователь {username} не найден в AD")

    dn = found["dn"]
    payload = dict(TEMPLATE_VALUES)
    if values:
        payload.update(values)
    if keep_identity:
        attrs = found.get("attributes") or {}
        for key in ("givenName", "sn", "middleName", "displayName", "mail"):
            current = attrs.get(key)
            if isinstance(current, list) and current:
                payload.pop(key, None)
            elif isinstance(current, str) and current:
                payload.pop(key, None)

    changes = {key: [(MODIFY_REPLACE, [value])] for key, value in payload.items()}
    if not conn.modify(dn, changes):
        raise UserScriptError(f"Не удалось обновить {dn}: {conn.result}")
    return dn


def fetch_access_token(
    username: str,
    password: str,
    client_id: str = KEYCLOAK_CLIENT_ID,
    client_secret: str | None = None,
) -> dict[str, Any]:
    _require_requests()
    data = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
        "scope": KEYCLOAK_SCOPE,
    }
    if client_secret:
        data["client_secret"] = client_secret
    response = requests.post(KEYCLOAK_TOKEN_URL, data=data, timeout=30)
    if response.status_code >= 400:
        raise UserScriptError(
            f"Keycloak вернул {response.status_code}: {response.text[:500]}"
        )
    body = response.json()
    token = body.get("access_token")
    if not token:
        raise UserScriptError(f"В ответе Keycloak нет access_token: {body}")
    return decode_jwt_payload(token)


def decode_jwt_payload(token: str) -> dict[str, Any]:
    import base64

    parts = token.split(".")
    if len(parts) < 2:
        raise UserScriptError("Некорректный JWT")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))


def bind_settings_from_env(args: argparse.Namespace) -> tuple[str, str, str, int, bool]:
    bind_user = args.bind_user or os.environ.get("AD_BIND_USER")
    bind_password = args.bind_password or os.environ.get("AD_BIND_PASSWORD")
    if not bind_user or not bind_password:
        raise UserScriptError(
            "Для LDAP нужны AD_BIND_USER и AD_BIND_PASSWORD "
            "(учётка с правами на OU=Techusers,OU=PROJECTS)"
        )
    host = args.ldap_host
    port = args.ldap_port
    use_ssl = not args.ldap_starttls
    return bind_user, bind_password, host, port, use_ssl


def cmd_create(args: argparse.Namespace) -> int:
    username = validate_username(args.username)
    password = validate_password(args.password)
    bind_user, bind_password, host, port, use_ssl = bind_settings_from_env(args)
    conn = ldap_connect(
        host,
        port,
        bind_user,
        bind_password,
        use_ssl=use_ssl,
        start_tls=args.ldap_starttls,
    )
    with conn:
        extra = {}
        if args.mail:
            extra["mail"] = args.mail
        if args.display_name:
            extra["displayName"] = args.display_name
        groups = [g.strip() for g in (args.member_of or "").replace("|", ";").split(";") if g.strip()]
        dn = create_ad_user(
            conn,
            username=username,
            password=password,
            ou=args.ou,
            extra_attrs=extra or None,
            group_dns=groups,
        )
    print(f"Создан пользователь {username}: {dn}")
    return 0


def cmd_fill(args: argparse.Namespace) -> int:
    username = validate_username(args.username)
    bind_user, bind_password, host, port, use_ssl = bind_settings_from_env(args)
    conn = ldap_connect(
        host,
        port,
        bind_user,
        bind_password,
        use_ssl=use_ssl,
        start_tls=args.ldap_starttls,
    )
    with conn:
        template_values = dict(TEMPLATE_VALUES)
        if args.from_template:
            source = search_user(conn, args.from_template, attributes=list(REQUIRED_AD_ATTRIBUTES))
            if not source:
                raise UserScriptError(f"Эталон {args.from_template} не найден в AD")
            src_attrs = source.get("attributes") or {}
            for key in REQUIRED_AD_ATTRIBUTES:
                value = src_attrs.get(key)
                if isinstance(value, list) and value:
                    template_values[key] = str(value[0])
                elif isinstance(value, str) and value:
                    template_values[key] = value
        dn = fill_ad_user(
            conn,
            username,
            values=template_values,
            keep_identity=not args.overwrite_identity,
        )
    print(f"Дозаполнены атрибуты {username}: {dn}")
    print("Заполненные поля:", ", ".join(REQUIRED_AD_ATTRIBUTES))
    return 0


def cmd_csv(args: argparse.Namespace) -> int:
    username = validate_username(args.username)
    password = validate_password(args.password)
    path = Path(args.output)
    write_users_csv(path, [csv_row(username, password, args.member_of or "")])
    print(f"CSV для импорта на портале: {path}")
    print("Портал: https://portal.msk.moscow.alfaintra.net/")
    print("Импорт: Работа с пользователями -> Импортировать пользователей")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    username = validate_username(args.username)
    password = args.password or (TICKET_PASSWORD if username.lower() == TICKET_USERNAME.lower() else "")
    password = validate_password(password)
    token = fetch_access_token(
        username=username,
        password=password,
        client_id=args.client_id,
        client_secret=args.client_secret or os.environ.get("KEYCLOAK_CLIENT_SECRET"),
    )
    missing = missing_claims(token)
    print(json.dumps(token, ensure_ascii=False, indent=2))
    if missing:
        print("Не хватает claim'ов:", ", ".join(missing), file=sys.stderr)
        return 2
    print("Все обязательные claim'ы присутствуют.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Создание тестового пользователя AD и проверка JWT Keycloak (NCINS-291)"
    )
    ldap = argparse.ArgumentParser(add_help=False)
    ldap.add_argument("--ldap-host", default=DEFAULT_LDAP_HOST, help="Хост DC / LDAP")
    ldap.add_argument("--ldap-port", type=int, default=DEFAULT_LDAP_PORT, help="Порт LDAP/LDAPS")
    ldap.add_argument("--ldap-starttls", action="store_true", help="STARTTLS вместо LDAPS")
    ldap.add_argument("--bind-user", help="Bind DN или DOMAIN\\user. Иначе AD_BIND_USER")
    ldap.add_argument("--bind-password", help="Пароль bind-учётки. Иначе AD_BIND_PASSWORD")
    ldap.add_argument("--ou", default=USER_OU, help="OU для создания пользователя")

    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", parents=[ldap], help="Создать пользователя в AD по LDAP")
    create.add_argument("--username", required=True)
    create.add_argument("--password", required=True)
    create.add_argument("--mail")
    create.add_argument("--display-name")
    create.add_argument("--member-of", help="DN групп через ';' или '|'")
    create.set_defaults(func=cmd_create)

    fill = sub.add_parser(
        "fill",
        parents=[ldap],
        help="Дозаполнить существующего пользователя атрибутами эталона u_m1n2y",
    )
    fill.add_argument("--username", default=TICKET_USERNAME)
    fill.add_argument("--from-template", default=TEMPLATE_USERNAME)
    fill.add_argument(
        "--overwrite-identity",
        action="store_true",
        help="Перезаписать ФИО и mail значениями эталона",
    )
    fill.set_defaults(func=cmd_fill)

    csv_cmd = sub.add_parser("csv", help="Сгенерировать Users.csv для импорта на портале AD")
    csv_cmd.add_argument("--username", required=True)
    csv_cmd.add_argument("--password", required=True)
    csv_cmd.add_argument("--member-of", default="", help="DN групп, разделитель в CSV: ', '")
    csv_cmd.add_argument("--output", default="Users.csv")
    csv_cmd.set_defaults(func=cmd_csv)

    verify = sub.add_parser("verify", help="Получить JWT Keycloak и проверить обязательные claim'ы")
    verify.add_argument("--username", default=TICKET_USERNAME)
    verify.add_argument("--password", default=None)
    verify.add_argument("--client-id", default=KEYCLOAK_CLIENT_ID)
    verify.add_argument("--client-secret", default=None)
    verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UserScriptError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
