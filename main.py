import json
import os
import hashlib
import base64
import time
from terrasnek.api import TFE
from google.cloud import storage

TFE_TOKEN = os.getenv("TFE_TOKEN", None)
TFE_URL = os.getenv("TFE_URL", "https://app.terraform.io")
TFE_ORG = os.getenv("TFE_ORG", None)
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", None)

if __name__ == "__main__":
    # Create the GCS client
    storage_client = storage.Client()

    # Retrieve the blob info from the GCS bucket
    blobs = storage_client.list_blobs(GCS_BUCKET_NAME)

    migration_targets = []

    # Read the migration targets from the file system
    with open("migration.json", "r") as f:
        migration_targets = json.loads(f.read())

    for mt in migration_targets:
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob_path = mt['gcs-blob-path']
        blob = bucket.blob(blob_path)
        statefile_name = blob.name.split("/")[-1]
        statefile_path = f"statefiles/{statefile_name}"
        blob.download_to_filename(statefile_path)

        # Add the local path we saved the statefile to
        # in the migration targets dict for usage later
        mt["statefile-local-path"] = statefile_path

    api = TFE(TFE_TOKEN, url=TFE_URL)
    api.set_organization(TFE_ORG)
    oauth_clients = api.oauth_clients.lst()
    # TODO: I should probably specify this as an env var in case there are many.
    oauth_client_id = api.oauth_clients.lst()["data"][0]["relationships"]["oauth-tokens"]["data"][0]["id"]

    for mt in migration_targets:
        # Configure our create payload with the data
        # from the migration targets JSON file
        create_ws_payload = {
            "data": {
                "attributes": {
                    "name": mt["workspace-name"],
                    "terraform_version": mt["tf-version"],
                    "working-directory": mt["working-dir"],
                    "vcs-repo": {
                        "identifier": mt["repo"],
                        "oauth-token-id": oauth_client_id,
                        "branch": mt["branch"],
                        "default-branch": True
                    }
                },
                "type": "workspaces"
            }
        }

        print(create_ws_payload)
        # Create a workspace with the VCS repo attached
        ws = api.workspaces.create(create_ws_payload)
        ws_id = ws["data"]["id"]

        # Read in the statefile contents we just pulled from GCS
        raw_state_bytes = None
        with open(mt["statefile-local-path"], "rb") as infile:
            raw_state_bytes = infile.read()

        # Perform a couple operations on the data required for the
        # create payload. See more detail here:
        # https://www.terraform.io/docs/cloud/api/state-versions.html
        state_hash = hashlib.md5()
        state_hash.update(raw_state_bytes)
        state_md5 = state_hash.hexdigest()
        state_b64 = base64.b64encode(raw_state_bytes).decode("utf-8")

        # Build the payload
        create_state_version_payload = {
            "data": {
                "type": "state-versions",
                "attributes": {
                    "serial": 1,
                    "md5": state_md5,
                    "state": state_b64
                }
            }
        }

        # State versions cannot be modified if the workspace isn't locked
        api.workspaces.lock(ws_id, {"reason": "migration script"})

        # Create the state version
        api.state_versions.create(ws_id, create_state_version_payload)

        # Unlock the workspace so other people can use it
        api.workspaces.unlock(ws_id)