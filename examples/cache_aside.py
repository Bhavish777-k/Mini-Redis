"""Cache-aside example using Fast-KV with a simulated primary database."""

from fastkv import FastKV

cache = FastKV(port=7001)
products = {"product:101": "Keyboard", "product:102": "Monitor"}


def get_product(key: str) -> str:
    cached = cache.get(key)
    if cached is not None:
        return cached

    product = products[key]
    cache.set(key, product, ttl=300)
    return product


def update_product(key: str, value: str) -> None:
    products[key] = value
    cache.delete(key)


if __name__ == "__main__":
    print(get_product("product:101"))
    update_product("product:101", "MechanicalKeyboard")
    print(get_product("product:101"))
