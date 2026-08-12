"""Display rules for the dashboard, kept out of app.py so they can be tested.

Nothing in here imports Streamlit. These are the functions that decide what the
board *says* about a row — which tier it falls into, how a return is phrased,
whether the pre-blend columns are worth drawing — and every one of them was
previously stranded inside a 3,600-line script where no test could reach it.
"""
