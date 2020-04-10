import json
import os
import hashlib
import base64
import time
from terrasnek.api import TFC
from google.cloud import storage

TFC_TOKEN = os.getenv("TFC_TOKEN", None)
TFC_OAUTH_TOKEN_ID = os.getenv("TFC_OAUTH_TOKEN_ID", None)
TFC_URL = os.getenv("TFC_URL", "https://app.terraform.io")
TFC_ORG = os.getenv("TFC_ORG", None)
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", None)

if __name__ == "__main__":
    migration_targets = []

    # Read the Migration Map from the file system into a Python dict
    with open("migration.json", "r") as f:
        migration_targets = json.loads(f.read())

    # Create the GCS client
    storage_client = storage.Client()

    # Create a Terraform Enterprise client with the TFC_TOKEN from the
    # environment
    api = TFC(TFC_TOKEN, url=TFC_URL)

    # Set the orgranization to work in for our client
    api.set_organization(TFC_ORG)

    for mt in migration_targets:
        # Connect to the bucket we want to download blobs from
        bucket = storage_client.bucket(GCS_BUCKET_NAME)

        # Create a blob object based on the blob path in the migration targets dict
        blob = bucket.blob(mt["gcs-blob-path"])

        # Extract the statefile name from the blob and use
        # it to define the path we want to save the statefile
        # locally
        statefile_name = blob.name.split("/")[-1]
        statefile_path = f"statefiles/{statefile_name}"

        # Download the statefile to the local path just defined
        blob.download_to_filename(statefile_path)

        # Add the local path we saved the statefile to
        # in the migration targets dict for usage later
        mt["statefile-local-path"] = statefile_path

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
                        "oauth-token-id": TFC_OAUTH_TOKEN_ID,
                        "branch": mt["branch"],
                        "default-branch": True
                    }
                },
                "type": "workspaces"
            }
        }

        # Create a workspace with the VCS repo attached
        ws = api.workspaces.create(create_ws_payload)
        # Save the workspace ID for usage when adding a state version
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