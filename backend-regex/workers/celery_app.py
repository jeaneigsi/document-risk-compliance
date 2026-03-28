from celery import Celery
from kombu import Queue

from app.config import get_settings

settings = get_settings()

# Création de l'application Celery
celery_app = Celery(
    "docs_regex_workers",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["workers.tasks"],
)

# Configuration Celery
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Paris",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.celery_task_timeout,
    task_soft_time_limit=settings.celery_task_timeout - 60,
    # Result settings
    result_expires=3600,
    result_extended=True,
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    # Routing
    task_routes={
        "workers.tasks.ingest_document": {"queue": "ingest"},
        "workers.tasks.process_search": {"queue": "search"},
        "workers.tasks.run_detection": {"queue": "detect"},
        "workers.tasks.run_eval_search": {"queue": "eval"},
        "workers.tasks.run_find_experiment": {"queue": "eval"},
    },
    # Ensure a default worker process consumes all app queues even without `-Q`.
    task_queues=(
        Queue("celery"),
        Queue("ingest"),
        Queue("search"),
        Queue("detect"),
        Queue("eval"),
    ),
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)


# Health check pour Celery
@celery_app.task(bind=True, name="workers.health_check")
def health_check_task(self) -> dict[str, str]:
    """Tâche de test pour vérifier que Celery fonctionne."""
    return {
        "status": "healthy",
        "task_id": self.request.id,
    }
