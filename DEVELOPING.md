This is a microservice, so tests are designed to be run from a mock web
application that calls to this service.  

## Quick start

To build the microservice and start it up, run:

    docker compose -f docker-compose.dev.yml up --build -d

To see logs:

    docker compose -f docker-compose.dev.yml logs -f

If you want to see debug logs, set `DEBUG` to `True` in `settings.py`.


## Testing

Once the above compose file is running, you can use the `mock_web_app`
container to run the tests against the `doctor` container:

    docker exec -it mock_web_app python3 -m unittest doctor.tests


## Building Images

Generally, images are automatically built and pushed to the docker repo when
PRs are merged. If it needs to happen manually, try this:

`make image --file docker/Makefile`

And pushed with:

`make push--file docker/Makefile`
