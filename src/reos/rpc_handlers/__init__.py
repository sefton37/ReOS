"""ReOS RPC handlers for the Cairn Tauri frontend.

These handlers are registered in Cairn's ui_rpc_server.py dispatch table
so the Tauri app can call ReOS functionality via JSON-RPC.

Convention: handlers accept (db: Database) or keyword params matching
the dispatch table pattern in ui_rpc_server.py. The db param is Cairn's
database — ReOS vitals handlers don't need it but accept it for
dispatch compatibility.
"""
