from asyncio import sleep
from collections import defaultdict, deque
from prodict import Prodict
from time import time
import asyncio
import ujson
import copy

from band import settings, dome, rpc, logger, app, run_task
from band.constants import NOTIFY_ALIVE, REQUEST_STATUS, OK, FRONTIER_SERVICE, DIRECTOR_SERVICE

from .structs import ServicePostion
from .constants import STATUS_RUNNING, STARTED_SET
from .helpers import merge, str2bool
from . import dock, state, image_navigator

from pprint import pprint


@dome.expose(path='/state')
async def get_state(name=None, prop=None):
    """
    Get list of services in state or get state of specified service
    Method for debug purposes
    """
    if name:
        if name in state:
            srv = await state.get(name)
            if prop and hasattr(srv, prop):
                return getattr(srv, prop)
            return srv.full_state()
    return list(state.state.keys())


@dome.expose(name='list')
async def lst(**params):
    """
    Containers list with status information
    """
    return list(
        [fs for fs in [s.full_state() for s in state.values()] if fs.state])


@dome.expose()
async def registrations(**params):
    """
    Provide global RPC registrations information
    Method for debug purposes
    """
    return state.registrations()
    # Iterating over containers and their methods


@dome.expose(name=NOTIFY_ALIVE)
async def sync_status(name, **params):
    """
    Listen for services promotions then ask their statuses.
    It some cases takes payload to reduce calls amount
    """
    await state.request_app_state(name)


@dome.expose(path='/show/{name}')
async def show(name, **params):
    """
    Returns container details
    """
    container = await dock.get(name)
    # check container exists
    if not container:
        return 404
    return container and container.full_state()


@dome.expose()
async def list_images(**params):
    """
    Available images list
    """
    return await image_navigator.lst()


@dome.expose()
async def list_configs(**params):
    """
    List of saved services configurations
    """
    return await state.configs()


@dome.expose(path='/status/{name}')
async def status_call(name, **params):
    """
    Ask service status
    """
    return await rpc.request(name, REQUEST_STATUS)


@dome.expose(path='/call/{name}/{method}')
async def call(name, method, **params):
    """
    Call service method
    """
    return await rpc.request(name, method, **params)


@dome.expose(path='/run/{name}')
async def run(name, **params):
    """
    Create image and run new container with service
    """

    params = Prodict(**params)

    if not image_navigator.is_native(name):
        return 404
    logger.debug('Called api.run with: %s', params)
    # Build options
    build_opts = {}

    if 'env' in params:
        build_opts['env'] = params['env']
    if 'nocache' in params:
        build_opts['nocache'] = str2bool(params['nocache'])
    if 'auto_remove' in params:
        build_opts['auto_remove'] = str2bool(params['auto_remove'])

    params['build_options'] = build_opts

    # Position on dashboard
    if 'pos' in params and params.pos:
        params.pos = ServicePostion(*params.pos.split('x'))

    # Get / create
    srv = await state.get(name, params=params)
    logger.info('request with params: %s. Using config: %s', params,
                srv.config)

    # save params and state only if successfully starter
    svc = await state.run_service(name, no_wait=True)
    return srv.full_state()


@dome.expose()
async def rebuild_all(**kwargs):
    """
    Rebuild all controlled containers
    """
    for name in await state.should_start():
        await run(name)
    return 200


@dome.expose(path='/restart/{name}')
async def restart(name, **params):
    """
    Restart service
    """
    svc = await state.restart_service(name, no_wait=True)
    return svc.full_state()


@dome.expose(path='/stop/{name}')
async def stop(name, **params):
    """
    Stop container. Only for persistent containers
    """
    # check container exists
    if not state.is_exists(name):
        return 404
    # executing main action
    svc = await state.stop_service(name, no_wait=True)
    return svc.full_state()


@dome.expose(path='/start/{name}')
async def start(name, **params):
    """
    Start
    """
    if not state.is_exists(name):
        return 404
    # executing main action
    svc = await state.start_service(name, no_wait=True)
    return svc.full_state()


@dome.expose(path='/rm/{name}')
async def remove(name, **params):
    """
    Unload/remove service
    """
    # check container exists
    if not state.is_exists(name):
        return 404
    svc = await state.remove_service(name, no_wait=True)
    return svc.full_state()
