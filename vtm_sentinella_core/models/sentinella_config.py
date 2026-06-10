from odoo import api, fields, models


class SentinellaConfig(models.Model):
    _name = "sentinella.config"
    _description = "Configuración Sentinella por Empresa"
    _rec_name = "company_id"

    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )

    # ── Liquidez ──────────────────────────────────────────────────────────────
    dias_caja_warning = fields.Integer("Días de Caja (aviso)", default=30)
    dias_caja_critical = fields.Integer("Días de Caja (crítico)", default=15)

    quick_ratio_warning = fields.Float("Quick Ratio (aviso)", digits=(4, 2), default=0.8)
    quick_ratio_critical = fields.Float("Quick Ratio (crítico)", digits=(4, 2), default=0.5)

    current_ratio_warning = fields.Float("Current Ratio (aviso)", digits=(4, 2), default=1.2)
    current_ratio_critical = fields.Float("Current Ratio (crítico)", digits=(4, 2), default=1.0)

    # ── Eficiencia ────────────────────────────────────────────────────────────
    dso_warning = fields.Integer("DSO (aviso)", default=60)
    dso_critical = fields.Integer("DSO (crítico)", default=90)

    ccc_warning = fields.Integer("CCC (aviso)", default=90)
    ccc_critical = fields.Integer("CCC (crítico)", default=120)

    # ── Solvencia ─────────────────────────────────────────────────────────────
    debt_ebitda_warning = fields.Float("Deuda/EBITDA (aviso)", digits=(4, 1), default=4.0)
    debt_ebitda_critical = fields.Float("Deuda/EBITDA (crítico)", digits=(4, 1), default=6.0)

    interest_coverage_warning = fields.Float(
        "Cobertura Intereses (aviso)", digits=(4, 1), default=2.5
    )
    interest_coverage_critical = fields.Float(
        "Cobertura Intereses (crítico)", digits=(4, 1), default=1.5
    )

    # ── Altman Z' ─────────────────────────────────────────────────────────────
    altman_z_warning = fields.Float("Altman Z' (zona gris)", digits=(4, 2), default=2.9)
    altman_z_critical = fields.Float("Altman Z' (distress)", digits=(4, 2), default=1.23)

    # ── Costos ────────────────────────────────────────────────────────────────
    opex_revenue_warning = fields.Float(
        "OPEX/Ventas % (aviso)", digits=(5, 1), default=30.0
    )
    opex_revenue_critical = fields.Float(
        "OPEX/Ventas % (crítico)", digits=(5, 1), default=40.0
    )
    financial_revenue_warning = fields.Float(
        "Gasto Financiero/Ventas % (aviso)", digits=(5, 1), default=5.0
    )
    financial_revenue_critical = fields.Float(
        "Gasto Financiero/Ventas % (crítico)", digits=(5, 1), default=8.0
    )
    cost_anomaly_pct = fields.Float(
        "% cambio para anomalía de gasto", digits=(5, 1), default=20.0
    )

    # ── Notificaciones ────────────────────────────────────────────────────────
    notify_managers = fields.Boolean("Notificar gerentes al estado rojo", default=True)

    _sql_constraints = [
        ("company_unique", "UNIQUE(company_id)", "Solo un registro de config por empresa."),
    ]

    @api.model
    def get_for_company(self, company_id=None):
        company = self.env["res.company"].browse(company_id) if company_id else self.env.company
        config = self.search([("company_id", "=", company.id)], limit=1)
        if not config:
            config = self.create({"company_id": company.id})
        return config
