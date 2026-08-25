FROM python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17

WORKDIR /srv
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && groupadd --gid 10001 plateos \
    && useradd --uid 10001 --gid plateos --no-create-home --shell /usr/sbin/nologin plateos

COPY --chown=plateos:plateos alembic.ini ./
COPY --chown=plateos:plateos alembic ./alembic
COPY --chown=plateos:plateos app ./app

# Settings-screen state lives here; a named volume copies this ownership and
# mode on first use so the non-root runtime can write it privately.
RUN install -d -o plateos -g plateos -m 0750 /srv/data

EXPOSE 8000
USER 10001:10001

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
