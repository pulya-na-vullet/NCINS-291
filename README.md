# NCINS-291 — тестовый пользователь AD для SFA / Keycloak

Тикет: **[SFA] Заполнить тестового пользователя данными в AD**.

В пользовательском Keycloak (`https://idp-test.alfaintra.net/auth/realms/users`, client `ufr-eos-ul-ncins`) claim'ы берутся из тестового Active Directory `msk.ad2012.loc`. У `adNcins` в AD не заполнены атрибуты, поэтому JWT сейчас без ФИО, должности, подразделения и полей `alfaMiisEq*`.

## Что нужно протестировать

После дозаполнения AD получить access token тем же scope, что на скриншотах:

`openid ufr-eos-ul-ncins-attributes profile groups-include-all email`

и сравнить набор полей с эталоном `u_m1n2y`.

| Claim в JWT | Откуда в AD | Сейчас у `adNcins` | Должно быть |
| --- | --- | --- | --- |
| `sAMAccountName` / `preferred_username` | `sAMAccountName` | `adNcins` | заполнено |
| `email` | `mail` | `msyakovlev@alfabank.ru` | заполнено |
| `given_name` | `givenName` | нет | заполнено |
| `family_name` | `sn` | нет | заполнено |
| `middle_name` | `middleName` | нет | заполнено |
| `name` / `displayName` | `displayName` | нет | заполнено |
| `title` | `title` | нет | заполнено |
| `department` | `department` | нет | заполнено |
| `alfaMiisEqNumber` | `alfaMiisEqNumber` | нет | например `9999` |
| `alfaMiisEqMnemonic` | `alfaMiisEqMnemonic` | нет | например `MAA6` |
| `alfaMiisEqProfile` | `alfaMiisEqProfile` | нет | например `1111` |

Группы эталона (`UFBIOM_USER`) копировать не обязательно: в тикете речь про **список заполненных параметров**, а не про членство. У `adNcins` уже есть свои группы (`EOS_Manager_UL`, `LINK-ROLE-M-Administrator`, …).

Проверки на стороне продукта SFA:

1. Логин тестовым пользователем `adNcins`.
2. В токене есть все claim'ы из таблицы.
3. Экраны оформления страховых продуктов ЮЛ/ИП читают ФИО, подразделение, мнемонику/код/профиль отделения EQ.
4. Регрессия: логин эталоном `u_m1n2y` по-прежнему отдаёт полный набор полей.

Готовая проверка токена:

```bash
python create_user.py verify --username adNcins --password "$ADNCINS_PASSWORD"
```

Код выхода `2` — в JWT нет обязательных claim'ов.

## Как создать / дозаполнить пользователя

Доступ к порталу: заявка в `http://itservice/ithelps/` → «Универсальная заявка на доступ» → ресурс **! ACTIVE DIRECTORY тестирование приложений**.

Портал: [https://portal.msk.moscow.alfaintra.net/](https://portal.msk.moscow.alfaintra.net/)

- Браузеры: Yandex ≥ 25.6, Edge, Chrome ≥ 120.
- OU по умолчанию: `OU=Users,OU=Techusers,OU=PROJECTS,DC=msk,DC=ad2012,DC=loc`
- Логин не длиннее 20 символов.
- Пароль по политике AD, **без** символа `;`.
- Импорт CSV — не больше 30 учёток за раз. Если учётка появилась на портале, но нет в AD — писать на `win_support`.

### Вариант A. Дозаполнить существующего `adNcins` (задача тикета)

Через LDAP (нужна учётка с правами на OU Techusers):

```bash
pip install -r requirements.txt
export AD_BIND_USER='MSK\your.login'
export AD_BIND_PASSWORD='...'
python create_user.py fill --username adNcins --from-template u_m1n2y
```

Вручную на портале: найти `adNcins` → «Базовые атрибуты» / «Все атрибуты» и заполнить те же поля, что у `u_m1n2y`.

### Вариант B. Создать нового пользователя скриптом

```bash
export AD_BIND_USER='MSK\your.login'
export AD_BIND_PASSWORD='...'
python create_user.py create --username adNcinsSfa --password 'Pe1fCLpx2hJc!'
```

### Вариант C. CSV для кнопки «Импортировать пользователей»

```bash
python create_user.py csv --username adNcinsSfa --password 'Pe1fCLpx2hJc!' --output Users.csv
```

Затем на портале: **Работа с пользователями и группами** → **Импортировать пользователей** → шаблон / этот CSV → **Запустить**.

Учётные данные из тикета (для verify, не для создания дубля):

- логин: `adNcins`
- пароль: см. тикет / переменная `ADNCINS_PASSWORD`
- эталон атрибутов: `u_m1n2y`
