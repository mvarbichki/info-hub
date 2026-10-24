from django.core.checks import Error, Tags, register
from django.db import connections


@register(Tags.database)
def mariadb_charset(app_configs, databases=None, **kwargs):
    """A MariaDB/MySQL database must be utf8mb4 with the collation the connection uses.

    Hosting panels often create databases as latin1 (no Cyrillic) or with another collation
    (text comparisons between the two then fail). Runs before `migrate`, so nothing is
    created in a wrong database.
    """
    errors = []
    for alias in databases or []:
        connection = connections[alias]
        if connection.vendor != "mysql":
            continue
        expected = connection.settings_dict["OPTIONS"].get("collation", "utf8mb4_unicode_ci")
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@character_set_database, @@collation_database")
            charset, collation = cursor.fetchone()
        if (charset, collation) != ("utf8mb4", expected):
            name = connection.settings_dict["NAME"]
            errors.append(Error(
                f"Database '{name}' is {charset} / {collation}, needs utf8mb4 / {expected}.",
                hint=f"Before the first migrate, run in phpMyAdmin: ALTER DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE {expected};",
                id="infohub.E001",
            ))
    return errors
