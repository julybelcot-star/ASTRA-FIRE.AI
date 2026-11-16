# ASTRA-FIRE AI V2

Starter structure for the hackathon. The scientific risk engine is **not implemented or validated** in this scaffold.

## Quick start

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

## Planned modules

- Overview
- Scientific Explorer (Library, Experiments, Measurements)
- AI Research Assistant (user uploads remain separate)
- Hazard Assessment
- Flame Simulation & Risk (shared risk engine)
- Admin Console (requires real authentication and authorization before deployment)

## Data model

Documents → Experiments → Measurements / Findings. Every measurement should include its units, source and experimental conditions.
