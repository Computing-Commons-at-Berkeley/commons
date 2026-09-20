# web - optional read-only UI

A disposable Streamlit companion over the same Git and SQLite state. It **never
writes**, needs no authentication, and no core community workflow depends on it.
Deleting this directory changes nothing for the community.

~~~bash
pip install -e ".[ui]"
streamlit run web/app.py
~~~

Requires `COMMUNITY_REPO_PATH` and (optionally) `RUNTIME_DIR` in the
environment, exactly like the bot.

Pages: Home, Feed, Projects, Berkeley, Knowledge, Resources, Search.
