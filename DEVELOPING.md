This is a microservice, so tests are designed to be run from a mock web
application that calls to this service.  

## Quick start

To build the microservice and start it up, run:

    docker compose up --build -d

To see logs:

    docker compose logs -f

If you want to see debug logs, set `DEBUG` to `True` in `settings.py`.


## Testing

Once the above compose file is running, you can use the `mock_web_app`
container to run the tests against the `doctor` container:

    docker exec -it mock_web_app python3 -m unittest doctor.tests


## Type checking

[pyrefly](https://pyrefly.org) type checks the codebase. Run it with:

    uv run pyrefly check

New code should include type hints and pass the check; new files go in the
`project-includes` section of `pyrefly.toml`. Pre-existing errors are
grandfathered in `.pyrefly-baseline.json`, so only new ones fail. Fixed errors
linger in the baseline until pruned, so occasionally run

    uv run pyrefly check --update-baseline

and commit the result. Don't update the baseline to silence errors in new or
changed code — fix the code instead.

Modules that are already clean under stricter settings are listed as
`sub-config` entries in `pyrefly.toml`; add modules there as they get cleaned
up.


## Building Images

Generally, images are automatically built and pushed to the docker repo when
PRs are merged. If it needs to happen manually, try this:

`make image --file docker/Makefile`

And pushed with:

`make push--file docker/Makefile`
