name: query-typedb description: Execute TypeQL read/write queries against the v3.0 database.
Query TypeDB

Use the Python driver. Pattern:python from typedb.driver import TypeDB, SessionType, TransactionType with TypeDB.core_driver(address) as driver: with driver.session(db_name, SessionType.DATA) as session: with session.transaction(TransactionType.READ) as tx: result = tx.query.fetch(query)