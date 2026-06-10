import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

STATE_SEL = [
    ("verde", "Costos bajo control"),
    ("amarillo", "Costos creciendo más rápido que ventas"),
    ("rojo", "Costos críticos — acción requerida"),
]


class SentinellaCost(models.Model):
    _name = "sentinella.cost"
    _description = "Análisis de Costos Sentinella"
    _order = "date_from desc, id desc"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    date_from = fields.Date("Desde", required=True)
    date_to = fields.Date("Hasta", required=True)
    period_label = fields.Char(compute="_compute_period_label", store=True)

    # ── Totales ───────────────────────────────────────────────────────────────
    total_revenue = fields.Monetary(currency_field="currency_id")
    total_cogs = fields.Monetary(currency_field="currency_id")
    total_opex = fields.Monetary(currency_field="currency_id")
    total_financial = fields.Monetary(currency_field="currency_id")
    total_expense = fields.Monetary(currency_field="currency_id")

    gross_margin_pct = fields.Float("Margen Bruto %", digits=(5, 1))
    ebitda_pct = fields.Float("EBITDA %", digits=(5, 1))
    opex_revenue_pct = fields.Float("OPEX/Ventas %", digits=(5, 1))
    financial_revenue_pct = fields.Float("Gasto Financiero/Ventas %", digits=(5, 1))

    # ── Comparativo vs período anterior ──────────────────────────────────────
    prev_revenue = fields.Monetary(currency_field="currency_id")
    prev_opex = fields.Monetary(currency_field="currency_id")
    revenue_change_pct = fields.Float("Var% Ventas", digits=(5, 1))
    opex_change_pct = fields.Float("Var% OPEX", digits=(5, 1))

    cost_state = fields.Selection(STATE_SEL, default="verde", string="Estado")

    line_ids = fields.One2many("sentinella.cost.line", "cost_id", string="Detalle de Gastos")

    @api.depends("date_from")
    def _compute_period_label(self):
        for rec in self:
            if rec.date_from:
                rec.period_label = rec.date_from.strftime("%B %Y").capitalize()
            else:
                rec.period_label = ""

    @api.model
    def compute_costs(self, month_offset=1):
        """Llamado por cron mensual. Analiza el mes anterior."""
        for company in self.env["res.company"].search([]):
            try:
                today = date.today()
                date_to = (today.replace(day=1) - relativedelta(days=1))
                date_from = date_to.replace(day=1)
                if month_offset > 1:
                    date_to -= relativedelta(months=month_offset - 1)
                    date_from = date_to.replace(day=1)

                cost = self.create({
                    "company_id": company.id,
                    "date_from": date_from,
                    "date_to": date_to,
                })
                cost._pull_costs()
                cost._eval_state()
                _logger.info("Sentinella: análisis de costos %s creado para %s", cost.id, company.name)
            except Exception as e:
                _logger.error("Sentinella: error análisis costos para %s: %s", company.name, e)

    def _pull_costs(self):
        self.ensure_one()
        company = self.company_id
        AML = self.env["account.move.line"]
        cfg = self.env["sentinella.config"].get_for_company(company.id)

        def period_total(types, date_from, date_to):
            domain = [
                ("company_id", "=", company.id),
                ("account_id.account_type", "in", types),
                ("move_id.state", "=", "posted"),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
            ]
            lines = AML.search(domain)
            return abs(sum(lines.mapped("balance")))

        df, dt = self.date_from, self.date_to
        prev_dt = df - relativedelta(days=1)
        prev_df = prev_dt.replace(day=1)

        # Período actual
        self.total_revenue = period_total(["income", "income_other"], df, dt)
        self.total_cogs = period_total(["expense_direct_cost"], df, dt)
        self.total_opex = period_total(["expense", "expense_depreciation"], df, dt)
        self.total_financial = period_total(["expense_financial_revenue"], df, dt)
        self.total_expense = self.total_cogs + self.total_opex + self.total_financial

        # Ratios
        rev = self.total_revenue or 1.0
        self.gross_margin_pct = (self.total_revenue - self.total_cogs) / rev * 100
        gross = self.total_revenue - self.total_cogs
        self.ebitda_pct = (gross - self.total_opex) / rev * 100
        self.opex_revenue_pct = self.total_opex / rev * 100
        self.financial_revenue_pct = self.total_financial / rev * 100

        # Período anterior
        self.prev_revenue = period_total(["income", "income_other"], prev_df, prev_dt)
        self.prev_opex = period_total(["expense", "expense_depreciation"], prev_df, prev_dt)
        prev_rev = self.prev_revenue or 1.0
        prev_op = self.prev_opex or 1.0
        self.revenue_change_pct = (self.total_revenue - self.prev_revenue) / prev_rev * 100
        self.opex_change_pct = (self.total_opex - self.prev_opex) / prev_op * 100

        # Líneas por cuenta
        self._build_cost_lines(df, dt, prev_df, prev_dt, cfg)

    def _build_cost_lines(self, df, dt, prev_df, prev_dt, cfg):
        self.ensure_one()
        company = self.company_id
        AML = self.env["account.move.line"]
        CostLine = self.env["sentinella.cost.line"]

        expense_types = {
            "expense_direct_cost": "cogs",
            "expense": "opex",
            "expense_depreciation": "opex",
            "expense_financial_revenue": "financial",
        }

        for atype, category in expense_types.items():
            domain_curr = [
                ("company_id", "=", company.id),
                ("account_id.account_type", "=", atype),
                ("move_id.state", "=", "posted"),
                ("date", ">=", df),
                ("date", "<=", dt),
            ]
            groups = AML.read_group(
                domain_curr,
                ["account_id", "balance:sum"],
                ["account_id"],
            )
            for g in groups:
                account = self.env["account.account"].browse(g["account_id"][0])
                amount_curr = abs(g["balance"])
                if amount_curr < 0.01:
                    continue

                domain_prev = [
                    ("company_id", "=", company.id),
                    ("account_id", "=", account.id),
                    ("move_id.state", "=", "posted"),
                    ("date", ">=", prev_df),
                    ("date", "<=", prev_dt),
                ]
                prev_lines = AML.search(domain_prev)
                amount_prev = abs(sum(prev_lines.mapped("balance")))

                prev_base = amount_prev or 1.0
                change_pct = (amount_curr - amount_prev) / prev_base * 100
                rev = self.total_revenue or 1.0
                pct_rev = amount_curr / rev * 100
                total_exp = self.total_expense or 1.0
                pct_total = amount_curr / total_exp * 100

                # Estado de la línea
                if change_pct > cfg.cost_anomaly_pct and amount_prev > 0:
                    alert_state = "anomalia"
                elif category == "opex" and pct_rev > cfg.opex_revenue_critical:
                    alert_state = "exceso"
                else:
                    alert_state = "normal"

                CostLine.create({
                    "cost_id": self.id,
                    "account_id": account.id,
                    "account_name": account.name,
                    "account_type_cat": category,
                    "amount_current": amount_curr,
                    "amount_prev": amount_prev,
                    "change_pct": change_pct,
                    "pct_of_revenue": pct_rev,
                    "pct_of_total": pct_total,
                    "alert_state": alert_state,
                })

    def _eval_state(self):
        self.ensure_one()
        cfg = self.env["sentinella.config"].get_for_company(self.company_id.id)
        has_anomaly = self.line_ids.filtered(lambda l: l.alert_state != "normal")

        if (
            self.opex_revenue_pct > cfg.opex_revenue_critical
            or self.financial_revenue_pct > cfg.financial_revenue_critical
            or self.opex_change_pct > 30
        ):
            self.cost_state = "rojo"
        elif (
            self.opex_revenue_pct > cfg.opex_revenue_warning
            or self.financial_revenue_pct > cfg.financial_revenue_warning
            or has_anomaly
        ):
            self.cost_state = "amarillo"
        else:
            self.cost_state = "verde"

        self.env["sentinella.recommendation"].generate_from_costs(self)
