"""Run inside an isolated Compose stack: scheduler writes, API server reads."""

from pathlib import Path
import sys
import time

from airflow.configuration import conf


NAME = "airflow-log-smoke.log"
MARKER = "airflow-authenticated-log-smoke\n"


def main():
    if sys.argv[1:] == ["write"]:
        path = Path(conf.get("logging", "base_log_folder")) / NAME
        path.write_text(MARKER)
        print("Scheduler wrote the log marker")
        return
    if sys.argv[1:] != ["read"]:
        raise SystemExit("Expected write or read")

    import requests
    from airflow.utils.log.file_task_handler import _fetch_logs_from_service

    # Deliberately use HTTP even though the API server shares the log volume:
    # a local-file read would not detect mismatched signing keys.
    url = f"http://airflow-scheduler:8793/log/{NAME}"
    for attempt in range(30):
        try:
            with _fetch_logs_from_service(url, NAME) as response:
                response.raise_for_status()
                assert response.text == MARKER, "Log content was lost or changed"
            with requests.get(url, timeout=5) as unsigned:
                assert unsigned.status_code in (401, 403), "Unsigned log request was accepted"
            print("Authenticated log read: HTTP 200; unsigned read rejected")
            return
        except requests.RequestException:
            if attempt == 29:
                raise
            time.sleep(1)


if __name__ == "__main__":
    main()
