import inspect

from typedb.driver import Database

print("Database methods/properties:")
for name, member in inspect.getmembers(Database):
    if not name.startswith("_"):
        print(f" - {name}")
