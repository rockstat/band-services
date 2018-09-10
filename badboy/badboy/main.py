import asyncio
import arrow
from itertools import count
from band import settings, logger, expose, response


@expose.handler()
async def test1(**params):
    return None

@expose.handler()
async def test2(**params):
    return response(params)


@expose.handler()
async def pix(**params):
    print(params)
    return response.pixel()


@expose.handler()
async def red(**params):
    return response.redirect('https://ya.ru')
