"""Streamlit web UI.

Thin layer over the existing modules:
- portfolio.store / portfolio.csv_import for state
- digest.build_digest for the per-stock card
- batch.run_batch for the dashboard fan-out
- render.render_digest_md is reused via st.markdown

Run via: `pintel ui` (or `streamlit run src/portfolio_intel/ui/app.py`).
"""
