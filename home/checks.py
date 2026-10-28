from django.core.checks import Error, Tags, register
from django.db import connections


@register(Tags.database)
def mariadb_database(app_configs, databases=None, **kwargs):
    """A MariaDB/MySQL database must be utf8mb4 with the connection's collation, and InnoDB.

    Hosting panels often create databases as latin1 (no Cyrillic) or with another collation
    (text comparisons between the two then fail), and some make MyISAM tables by default (no
    transactions, keys too short for Wagtail). The connection asks for InnoDB (settings), so
    other tables can only come from before that. Runs before `migrate`, so nothing more is
    created in a wrong database.
    """
    errors = []
    for alias in databases or []:
        connection = connections[alias]
        if connection.vendor != "mysql":
            continue
        name = connection.settings_dict["NAME"]
        expected = connection.settings_dict["OPTIONS"].get("collation", "utf8mb4_unicode_ci")
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@character_set_database, @@collation_database")
            charset, collation = cursor.fetchone()
            cursor.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' AND ENGINE <> 'InnoDB'"
            )
            not_innodb = [row[0] for row in cursor.fetchall()]
        if (charset, collation) != ("utf8mb4", expected):
            errors.append(Error(
                f"Database '{name}' is {charset} / {collation}, needs utf8mb4 / {expected}.",
                hint=f"Before the first migrate, run in phpMyAdmin: ALTER DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE {expected};",
                id="infohub.E001",
            ))
        if not_innodb:
            errors.append(Error(
                f"Database '{name}' has {len(not_innodb)} tables that are not InnoDB (e.g. {not_innodb[0]}).",
                hint="They were made by an earlier migrate with the server's default engine. If the site has no data yet: "
                     f"phpMyAdmin → {name} → Structure → Check all → Drop, then run migrate again.",
                id="infohub.E002",
            ))
    return errors
