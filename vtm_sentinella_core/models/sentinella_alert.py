from odoo import fields, models


class SentinellaAlert(models.Model):
    _name = "sentinella.alert"
    _description = "Alerta Sentinella por KPI"
    _order = "date desc, state desc"

    snapshot_id = fields.Many2one("sentinella.snapshot", required=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company", related="snapshot_id.company_id", store=True
    )
    date = fields.Date(related="snapshot_id.date", store=True)

    kpi_name = fields.Char("KPI")
    kpi_label = fields.Char("Indicador")
    kpi_value = fields.Float("Valor", digits=(10, 2))
    threshold = fields.Float("Umbral crítico", digits=(10, 2))

    state = fields.Selection(
        [("amarillo", "Precaución"), ("rojo", "Crítico")],
        string="Estado",
        required=True,
    )
    notified = fields.Boolean("Notificado", default=False)
