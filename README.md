### Set env vars
```
export GOOGLE_APPLICATION_CREDENTIALS=""
export GCS_BUCKET_NAME=""
export TFC_TOKEN=""
export TFC_ORG=""
export TFC_URL=""
export TFC_OAUTH_TOKEN_ID=""
```

### Run Script

First, update `migration.json`. Probably a good idea to use
a `venv` and you must use Python 3.

```
pip install -i pip-reqs.txt
python main.py
```
