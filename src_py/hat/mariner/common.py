import importlib.resources

from hat import json


with importlib.resources.as_file(importlib.resources.files(__package__) /
                                 'json_schema_repo.json') as _path:
    json_schema_repo: json.SchemaRepository = json.merge_schema_repositories(
        json.json_schema_repo,
        json.decode_file(_path))
    """JSON schema repository"""
