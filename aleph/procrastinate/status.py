"""
Map procrastinate status table to old status model for current status api
"""

from typing import Any

from openaleph_procrastinate.status import get_status

from aleph.logic.aggregator import get_aggregator_name
from aleph.model.collection import Collection

FINISHED_JOBS = ["succeeded"]
RUNNING_JOBS = ["doing"]
PENDING_JOBS = ["todo"]
FAILED_JOBS = ["failed"]
CANCELLED_JOBS = ["aborted", "aborting", "cancelled"]


def get_active_collections_status(
    include_collection_data: bool | None = True,
) -> list[dict[str, Any]]:
    from aleph.views.serializers import CollectionSerializer

    results: list[dict[str, Any]] = []
    results = []
    # get the job status from openaleph_procrastinate
    jobs_status = get_status()
    # get the Collection serializer
    serializer = CollectionSerializer(nested=True)

    for collection_name in jobs_status:
        # periodic tasks don't have a collection_id
        if not collection_name:
            continue

        collection_status = {"dataset": collection_name}

        if include_collection_data:  # used for api, not for prometheus
            collection_id = int(collection_name.split("_")[-1])
            collection_obj = Collection.by_id(collection_id, deleted=True)
            if collection_obj is not None:
                collection_status["collection"] = serializer.serialize(
                    collection_obj.to_dict()
                )

        # convert the status from openaleph_procrastinate to the structure of the /status API
        stages = {}
        for jobs_status_per_stage in jobs_status[collection_name]:
            stage = jobs_status_per_stage["stage"]
            finished_jobs = (
                jobs_status_per_stage["number_of_jobs"]
                if jobs_status_per_stage["status_of_jobs"] in FINISHED_JOBS
                else 0
            )
            running_jobs = (
                jobs_status_per_stage["number_of_jobs"]
                if jobs_status_per_stage["status_of_jobs"] in RUNNING_JOBS
                else 0
            )
            pending_jobs = (
                jobs_status_per_stage["number_of_jobs"]
                if jobs_status_per_stage["status_of_jobs"] in PENDING_JOBS
                else 0
            )
            if stage in stages:
                stages[stage]["pending"] += pending_jobs
                stages[stage]["running"] += running_jobs
                stages[stage]["finished"] += finished_jobs
            else:
                stages[stage] = {
                    "job_id": "",
                    "stage": stage,
                    "pending": pending_jobs,
                    "running": running_jobs,
                    "finished": finished_jobs,
                }

        collection_status["jobs"] = [stages[stage] for stage in stages]
        collection_status["finished"] = sum(
            [stages[stage]["finished"] for stage in stages]
        )
        collection_status["running"] = sum(
            [stages[stage]["running"] for stage in stages]
        )
        collection_status["pending"] = sum(
            [stages[stage]["pending"] for stage in stages]
        )

        # FIXME this should happen somewhere else
        # find out if it is actually running currently:
        if collection_status["running"] + collection_status["pending"]:
            results.append(collection_status)

    return results


def get_collection_status(collection: Collection) -> dict[str, Any]:
    dataset = get_aggregator_name(collection)
    for collection_status in get_active_collections_status():
        if collection_status["dataset"] == dataset:
            return collection_status
    return {"finished": 0, "running": 0, "pending": 0, "jobs": []}
