# The app talks to Microsoft SQL Server through pyodbc, so the container
# needs the Microsoft ODBC driver, not just the Python packages.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# msodbcsql18 is the ODBC driver pyodbc needs. The unixODBC base and the
# unixodbc-dev headers are required to install it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
       unixodbc unixodbc-dev util-linux \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
       | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
       > /etc/apt/sources.list.d/mssql-release.list \
    && sed -i 's|deb \[|deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg |' \
       /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
       msodbcsql18 mssql-tools18 unixodbc \
    && apt-get purge -y gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY gacha.json ./
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
# The shop config is written at runtime, so the folder has to be writable
# by the unprivileged user.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /srv/app/data \
    && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8080

# The platform injects the port; the default is what Render and Railway
# expect when nothing is set.
ENV PORT=8080 \
    HOST=0.0.0.0 \
    GACHA_FILE=/srv/app/data/gacha.json

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["sh", "-c", "python -m uvicorn app.main:app --host ${HOST} --port ${PORT}"]
