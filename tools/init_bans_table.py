"""Create the optional admin tables (idempotent).

`gacha_bans` holds the banned accounts, `gacha_admin_log` holds what the
admins did and `gacha_admins` holds the web console's own admin list,
which is kept in step with the LuckPerms group on the server.
All three are optional: the app turns the feature off when the table is
missing.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyodbc  # noqa: E402

from app.config import SQL_DATABASE, SQL_SERVER  # noqa: E402

DDL = """
IF OBJECT_ID('gacha_bans') IS NULL
CREATE TABLE gacha_bans (
    player NVARCHAR(450) NOT NULL,
    reason NVARCHAR(450) NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL,
    CONSTRAINT PK_gacha_bans PRIMARY KEY (player)
);

IF OBJECT_ID('gacha_admin_log') IS NULL
CREATE TABLE gacha_admin_log (
    id INT IDENTITY(1,1) NOT NULL,
    admin NVARCHAR(450) NOT NULL,
    action NVARCHAR(450) NOT NULL,
    target NVARCHAR(450) NOT NULL DEFAULT '',
    detail NVARCHAR(450) NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL,
    CONSTRAINT PK_gacha_admin_log PRIMARY KEY (id)
);

IF OBJECT_ID('gacha_admins') IS NULL
CREATE TABLE gacha_admins (
    name NVARCHAR(450) NOT NULL,
    source NVARCHAR(450) NOT NULL DEFAULT 'web',
    created_at BIGINT NOT NULL,
    CONSTRAINT PK_gacha_admins PRIMARY KEY (name)
);
"""

cnstr = (f"Driver={{ODBC Driver 18 for SQL Server}};Server={SQL_SERVER};"
         f"Database={SQL_DATABASE};Trusted_Connection=yes;Encrypt=yes;"
         "TrustServerCertificate=yes;")
with pyodbc.connect(cnstr, timeout=30, autocommit=True) as cn:
    cn.cursor().execute(DDL)
print("gacha_bans + gacha_admin_log + gacha_admins ready")
