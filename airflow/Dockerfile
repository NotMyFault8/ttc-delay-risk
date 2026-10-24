FROM apache/airflow:2.10.5-python3.12

USER root
RUN python -m venv /opt/ttc-delay-risk/.venv
COPY requirements.lock /tmp/ttc-requirements.lock
RUN /opt/ttc-delay-risk/.venv/bin/pip install --no-cache-dir -r /tmp/ttc-requirements.lock
COPY pyproject.toml /opt/ttc-delay-risk/
COPY src /opt/ttc-delay-risk/src
RUN /opt/ttc-delay-risk/.venv/bin/pip install --no-deps /opt/ttc-delay-risk
COPY airflow/dags /opt/airflow/dags
RUN mkdir -p /opt/ttc-delay-risk/data && chown -R airflow:0 /opt/ttc-delay-risk /opt/airflow/dags

USER airflow

