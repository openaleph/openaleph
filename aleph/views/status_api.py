import logging

from flask import Blueprint, request
from openaleph_procrastinate.status import get_status as get_job_status

from aleph.model import Collection
from aleph.views.serializers import CollectionSerializer
from aleph.views.util import jsonify, require

log = logging.getLogger(__name__)
blueprint = Blueprint("status_api", __name__)

FINISHED_JOBS = ["succeeded"]
RUNNING_JOBS = ["doing"]
PENDING_JOBS = ["todo"]
FAILED_JOBS = ["failed"]
CANCELLED_JOBS = ["aborted", "aborting", "cancelled"]


@blueprint.route("/api/2/status", methods=["GET"])
def status():
    """
    ---
    get:
      summary: Get an overview of collections and exports being processed
      description: >
        List collections being processed currently and pending task counts
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SystemStatusResponse'
      tags:
      - System
    """
    require(request.authz.logged_in)
    request.rate_limit = None

    results = []
    # get the job status from openaleph_procrastinate
    jobs_status = get_job_status()
    # get serialized collection metadata from ftm_store
    serializer = CollectionSerializer(nested=True)

    for collection_name in jobs_status:
        # periodic tasks don't have a collection_id
        if not collection_name:
            continue

        collection_status = {}

        # if the current user can read the current collection, add metadata
        collection_id = int(collection_name.split("_")[-1])
        if not request.authz.can(collection_id, request.authz.READ):
            continue
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

    return jsonify({"results": results, "total": len(results)})
