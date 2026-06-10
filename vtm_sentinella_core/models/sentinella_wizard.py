from odoo import api, fields, models


class SentinellaWizard(models.TransientModel):
    _name = "sentinella.wizard"
    _description = "Wizard de datos Sentinella para el dashboard OWL"

    @api.model
    def get_sentinel_data(self, options=None):
        """Retorna el payload completo para el dashboard OWL."""
        options = options or {}
        company = self.env["res.company"].browse(options.get("company_id")) if options.get("company_id") else self.env.company

        # Último snapshot
        snap = self.env["sentinella.snapshot"].search(
            [("company_id", "=", company.id)], limit=1, order="date desc"
        )

        # Último análisis de costos
        cost = self.env["sentinella.cost"].search(
            [("company_id", "=", company.id)], limit=1, order="date_from desc"
        )

        # Historial Altman Z' (últimos 30 snapshots)
        history = self.env["sentinella.snapshot"].search(
            [("company_id", "=", company.id)], limit=30, order="date asc"
        )

        # Recomendaciones abiertas
        recs = self.env["sentinella.recommendation"].search([
            ("company_id", "=", company.id),
            ("state", "in", ["abierta", "en_proceso"]),
        ], order="priority asc, date desc", limit=20)

        return {
            "meta": self._build_meta(company, snap),
            "kpis": self._build_kpis(snap),
            "overall_state": snap.overall_state if snap else "verde",
            "altman_history": self._build_altman_history(history),
            "costs": self._build_costs(cost),
            "recommendations": self._build_recommendations(recs),
            "companies": self._get_companies(),
        }

    def _build_meta(self, company, snap):
        return {
            "company_id": company.id,
            "company_name": company.name,
            "date": str(snap.date) if snap else "",
            "currency_id": company.currency_id.id,
            "currency_symbol": company.currency_id.symbol,
        }

    def _build_kpis(self, snap):
        if not snap:
            return []
        kpi_defs = [
            ("dias_caja", "Días de Caja", "días", "dias_caja_state", False),
            ("quick_ratio", "Quick Ratio", "x", "quick_ratio_state", False),
            ("current_ratio", "Current Ratio", "x", "current_ratio_state", False),
            ("dso", "DSO (Cobro)", "días", "dso_state", True),
            ("dpo", "DPO (Pago)", "días", None, True),
            ("dio", "DIO (Inventario)", "días", None, True),
            ("ccc", "CCC", "días", "ccc_state", True),
            ("debt_ebitda", "Deuda/EBITDA", "x", "debt_ebitda_state", True),
            ("interest_coverage", "Cob. Intereses", "x", "interest_coverage_state", False),
            ("altman_z", "Altman Z'", "", "altman_z_state", False),
        ]
        result = []
        for key, label, unit, state_field, higher_is_worse in kpi_defs:
            value = getattr(snap, key, 0.0)
            state = getattr(snap, state_field, "verde") if state_field else "verde"
            result.append({
                "key": key,
                "label": label,
                "value": round(value, 2),
                "unit": unit,
                "state": state,
                "higher_is_worse": higher_is_worse,
            })
        return result

    def _build_altman_history(self, history):
        return [
            {"date": str(s.date), "z": round(s.altman_z, 2), "state": s.altman_z_state}
            for s in history
        ]

    def _build_costs(self, cost):
        if not cost:
            return {}
        lines = []
        for l in cost.line_ids.sorted(key=lambda x: x.amount_current, reverse=True)[:15]:
            lines.append({
                "account": l.account_name,
                "category": l.account_type_cat,
                "current": round(l.amount_current, 2),
                "prev": round(l.amount_prev, 2),
                "change_pct": round(l.change_pct, 1),
                "pct_revenue": round(l.pct_of_revenue, 1),
                "pct_total": round(l.pct_of_total, 1),
                "state": l.alert_state,
            })
        # Top 6 para pie chart
        top6 = sorted(lines, key=lambda x: x["current"], reverse=True)[:6]
        others = sum(l["current"] for l in lines[6:])
        pie_labels = [l["account"] for l in top6]
        pie_values = [l["current"] for l in top6]
        if others > 0:
            pie_labels.append("Otros")
            pie_values.append(round(others, 2))

        return {
            "period_label": cost.period_label,
            "total_revenue": round(cost.total_revenue, 2),
            "total_opex": round(cost.total_opex, 2),
            "total_cogs": round(cost.total_cogs, 2),
            "total_financial": round(cost.total_financial, 2),
            "gross_margin_pct": round(cost.gross_margin_pct, 1),
            "ebitda_pct": round(cost.ebitda_pct, 1),
            "opex_pct": round(cost.opex_revenue_pct, 1),
            "financial_pct": round(cost.financial_revenue_pct, 1),
            "revenue_change_pct": round(cost.revenue_change_pct, 1),
            "opex_change_pct": round(cost.opex_change_pct, 1),
            "cost_state": cost.cost_state,
            "lines": lines,
            "pie_labels": pie_labels,
            "pie_values": pie_values,
        }

    def _build_recommendations(self, recs):
        category_icons = {
            "reduccion_costo": "💰",
            "aumento_ingreso": "📈",
            "liquidez": "💧",
            "riesgo_cliente": "⚠️",
            "riesgo_proveedor": "🚚",
            "alerta_operativa": "🔴",
        }
        result = []
        for r in recs:
            result.append({
                "id": r.id,
                "category": r.category,
                "category_label": dict(r._fields["category"].selection).get(r.category, ""),
                "icon": category_icons.get(r.category, "📌"),
                "priority": r.priority,
                "title": r.title,
                "body": r.body or "",
                "impact": round(r.impact, 2),
                "state": r.state,
                "date": str(r.date),
            })
        return result

    def _get_companies(self):
        companies = self.env["res.company"].search([])
        return [{"id": c.id, "name": c.name} for c in companies]

    @api.model
    def action_update_recommendation(self, rec_id, new_state):
        rec = self.env["sentinella.recommendation"].browse(rec_id)
        if rec.exists():
            rec.state = new_state
        return True

    @api.model
    def action_compute_now(self, company_id=None):
        """Fuerza cómputo inmediato desde el dashboard."""
        self.env["sentinella.snapshot"].compute_kpis()
        self.env["sentinella.cost"].compute_costs()
        return True
