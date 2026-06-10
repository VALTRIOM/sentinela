import logging
from datetime import date, timedelta
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

STATE_SEL = [("verde", "Verde"), ("amarillo", "Amarillo"), ("rojo", "Rojo")]


class SentinellaSnapshot(models.Model):
    _name = "sentinella.snapshot"
    _description = "Snapshot Financiero Sentinella"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    date = fields.Date(default=fields.Date.today, index=True)
    computed_by = fields.Many2one("res.users")
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)

    # ── Balances base (en moneda de la empresa) ───────────────────────────────
    cash = fields.Monetary(currency_field="currency_id")
    ar_balance = fields.Monetary(currency_field="currency_id")
    ap_balance = fields.Monetary(currency_field="currency_id")
    inventory_value = fields.Monetary(currency_field="currency_id")
    revenue_ltm = fields.Monetary(currency_field="currency_id")
    cogs_ltm = fields.Monetary(currency_field="currency_id")
    opex_ltm = fields.Monetary(currency_field="currency_id")
    ebitda_ltm = fields.Monetary(currency_field="currency_id")
    ebit_ltm = fields.Monetary(currency_field="currency_id")
    financial_exp = fields.Monetary(currency_field="currency_id")
    net_debt = fields.Monetary(currency_field="currency_id")
    current_assets = fields.Monetary(currency_field="currency_id")
    current_liab = fields.Monetary(currency_field="currency_id")
    total_assets = fields.Monetary(currency_field="currency_id")
    total_debt = fields.Monetary(currency_field="currency_id")
    retained_earn = fields.Monetary(currency_field="currency_id")
    net_wc = fields.Monetary(currency_field="currency_id")

    # ── KPIs calculados ───────────────────────────────────────────────────────
    dias_caja = fields.Float(digits=(10, 1))
    quick_ratio = fields.Float(digits=(10, 2))
    current_ratio = fields.Float(digits=(10, 2))
    dso = fields.Float(digits=(10, 1))
    dpo = fields.Float(digits=(10, 1))
    dio = fields.Float(digits=(10, 1))
    ccc = fields.Float(digits=(10, 1))
    debt_ebitda = fields.Float(digits=(10, 1))
    interest_coverage = fields.Float(digits=(10, 1))
    altman_z = fields.Float("Altman Z'", digits=(10, 2))

    # ── Estados semáforo por KPI ──────────────────────────────────────────────
    dias_caja_state = fields.Selection(STATE_SEL, default="verde")
    quick_ratio_state = fields.Selection(STATE_SEL, default="verde")
    current_ratio_state = fields.Selection(STATE_SEL, default="verde")
    dso_state = fields.Selection(STATE_SEL, default="verde")
    ccc_state = fields.Selection(STATE_SEL, default="verde")
    debt_ebitda_state = fields.Selection(STATE_SEL, default="verde")
    interest_coverage_state = fields.Selection(STATE_SEL, default="verde")
    altman_z_state = fields.Selection(STATE_SEL, default="verde")

    overall_state = fields.Selection(
        STATE_SEL, default="verde", tracking=True, string="Estado Global"
    )

    alert_ids = fields.One2many("sentinella.alert", "snapshot_id", string="Alertas")
    alert_count = fields.Integer(compute="_compute_alert_count")

    @api.depends("alert_ids")
    def _compute_alert_count(self):
        for rec in self:
            rec.alert_count = len(rec.alert_ids)

    # ── Motor de cómputo ──────────────────────────────────────────────────────

    @api.model
    def compute_kpis(self):
        """Llamado por ir.cron diariamente."""
        for company in self.env["res.company"].search([]):
            try:
                snap = self.create({
                    "company_id": company.id,
                    "date": fields.Date.today(),
                    "computed_by": self.env.uid,
                })
                snap._pull_balances()
                snap._calc_kpis()
                snap._eval_states()
                snap._trigger_recommendations()
                snap._notify_if_red()
                _logger.info("Sentinella: snapshot %s creado para %s", snap.id, company.name)
            except Exception as e:
                _logger.error("Sentinella: error en cómputo para %s: %s", company.name, e)

    def _pull_balances(self):
        self.ensure_one()
        company = self.company_id
        today = fields.Date.today()
        date_12m = today - timedelta(days=365)

        AML = self.env["account.move.line"]
        ACC = self.env["account.account"]

        def balance_by_types(types):
            accounts = ACC.search([
                ("company_id", "=", company.id),
                ("account_type", "in", types),
            ])
            return sum(accounts.mapped("current_balance")) if accounts else 0.0

        def revenue_period(types, date_from, date_to):
            domain = [
                ("company_id", "=", company.id),
                ("account_id.account_type", "in", types),
                ("move_id.state", "=", "posted"),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
            ]
            lines = AML.search(domain)
            return abs(sum(lines.mapped("balance")))

        # Activos líquidos
        self.cash = balance_by_types(["asset_cash"])
        self.ar_balance = balance_by_types(["asset_receivable"])

        # Pasivos
        self.ap_balance = abs(balance_by_types(["liability_payable"]))
        self.current_liab = abs(balance_by_types([
            "liability_payable", "liability_current"
        ]))

        # Inventario
        svl = self.env["stock.valuation.layer"].search([("company_id", "=", company.id)])
        self.inventory_value = sum(svl.mapped("value")) if svl else 0.0

        # Activo circulante
        self.current_assets = balance_by_types([
            "asset_cash", "asset_receivable", "asset_current"
        ])

        # Activos y deuda total
        self.total_assets = balance_by_types([
            "asset_cash", "asset_receivable", "asset_current",
            "asset_non_current", "asset_fixed",
        ])
        self.total_debt = abs(balance_by_types([
            "liability_payable", "liability_current", "liability_non_current"
        ]))

        # Capital retenido
        self.retained_earn = balance_by_types(["equity_unaffected"])

        # Capital de trabajo neto
        self.net_wc = self.current_assets - self.current_liab

        # P&L LTM
        self.revenue_ltm = revenue_period(["income", "income_other"], date_12m, today)
        self.cogs_ltm = revenue_period(["expense_direct_cost"], date_12m, today)
        self.opex_ltm = revenue_period(["expense", "expense_depreciation"], date_12m, today)
        self.financial_exp = revenue_period(["expense_financial_revenue"], date_12m, today)

        # EBITDA / EBIT aproximados
        gross_profit = self.revenue_ltm - self.cogs_ltm
        self.ebit_ltm = gross_profit - self.opex_ltm
        depreciation = revenue_period(["expense_depreciation"], date_12m, today)
        self.ebitda_ltm = self.ebit_ltm + depreciation

        # Deuda neta (deuda total − caja)
        self.net_debt = max(self.total_debt - self.cash, 0.0)

    def _calc_kpis(self):
        self.ensure_one()
        daily_opex = (self.opex_ltm + self.cogs_ltm) / 365.0 if (self.opex_ltm + self.cogs_ltm) > 0 else 1.0

        self.dias_caja = self.cash / daily_opex if daily_opex else 0.0
        self.quick_ratio = (self.cash + self.ar_balance) / self.current_liab if self.current_liab else 0.0
        self.current_ratio = self.current_assets / self.current_liab if self.current_liab else 0.0
        self.dso = (self.ar_balance / self.revenue_ltm * 365) if self.revenue_ltm else 0.0
        self.dpo = (self.ap_balance / self.cogs_ltm * 365) if self.cogs_ltm else 0.0
        self.dio = (self.inventory_value / self.cogs_ltm * 365) if self.cogs_ltm else 0.0
        self.ccc = self.dso + self.dio - self.dpo
        self.debt_ebitda = self.net_debt / self.ebitda_ltm if self.ebitda_ltm > 0 else 99.0
        self.interest_coverage = self.ebit_ltm / self.financial_exp if self.financial_exp > 0 else 99.0

        # Altman Z' (modelo de empresas no cotizadas)
        if self.total_assets > 0 and self.total_debt > 0:
            x1 = self.net_wc / self.total_assets
            x2 = self.retained_earn / self.total_assets
            x3 = self.ebit_ltm / self.total_assets
            x4 = (self.total_assets - self.total_debt) / self.total_debt
            x5 = self.revenue_ltm / self.total_assets
            self.altman_z = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * x4 + 0.998 * x5
        else:
            self.altman_z = 0.0

    def _kpi_state(self, value, warning, critical, higher_is_worse=True):
        """Retorna 'verde'/'amarillo'/'rojo' según umbrales."""
        if higher_is_worse:
            if value >= critical:
                return "rojo"
            if value >= warning:
                return "amarillo"
            return "verde"
        else:
            if value <= critical:
                return "rojo"
            if value <= warning:
                return "amarillo"
            return "verde"

    def _eval_states(self):
        self.ensure_one()
        cfg = self.env["sentinella.config"].get_for_company(self.company_id.id)
        Alert = self.env["sentinella.alert"]

        kpis = [
            ("dias_caja", "Días de Caja", self.dias_caja, cfg.dias_caja_warning, cfg.dias_caja_critical, False),
            ("quick_ratio", "Quick Ratio", self.quick_ratio, cfg.quick_ratio_warning, cfg.quick_ratio_critical, False),
            ("current_ratio", "Current Ratio", self.current_ratio, cfg.current_ratio_warning, cfg.current_ratio_critical, False),
            ("dso", "DSO", self.dso, cfg.dso_warning, cfg.dso_critical, True),
            ("ccc", "CCC", self.ccc, cfg.ccc_warning, cfg.ccc_critical, True),
            ("debt_ebitda", "Deuda/EBITDA", self.debt_ebitda, cfg.debt_ebitda_warning, cfg.debt_ebitda_critical, True),
            ("interest_coverage", "Cobertura Intereses", self.interest_coverage, cfg.interest_coverage_warning, cfg.interest_coverage_critical, False),
            ("altman_z", "Altman Z'", self.altman_z, cfg.altman_z_warning, cfg.altman_z_critical, False),
        ]

        states = []
        for key, label, value, warn, crit, hiw in kpis:
            st = self._kpi_state(value, warn, crit, hiw)
            setattr(self, f"{key}_state", st)
            states.append(st)
            if st in ("amarillo", "rojo"):
                Alert.create({
                    "snapshot_id": self.id,
                    "kpi_name": key,
                    "kpi_label": label,
                    "kpi_value": value,
                    "threshold": crit,
                    "state": st,
                })

        if "rojo" in states:
            self.overall_state = "rojo"
        elif "amarillo" in states:
            self.overall_state = "amarillo"
        else:
            self.overall_state = "verde"

    def _trigger_recommendations(self):
        self.ensure_one()
        self.env["sentinella.recommendation"].generate_from_snapshot(self)

    def _notify_if_red(self):
        self.ensure_one()
        if self.overall_state != "rojo":
            return
        cfg = self.env["sentinella.config"].get_for_company(self.company_id.id)
        if not cfg.notify_managers:
            return

        red_kpis = self.alert_ids.filtered(lambda a: a.state == "rojo")
        body = "<b>🔴 Sentinella — Alerta Crítica</b><br/>"
        body += f"Empresa: <b>{self.company_id.name}</b><br/>"
        body += f"Fecha: {self.date}<br/><br/>"
        body += "<b>KPIs en estado ROJO:</b><ul>"
        for a in red_kpis:
            body += f"<li>{a.kpi_label}: {a.kpi_value:.2f}</li>"
        body += "</ul>"

        self.message_post(body=body, subject="Sentinella — Alerta Crítica", message_type="email")

    def action_view_alerts(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Alertas",
            "res_model": "sentinella.alert",
            "view_mode": "list,form",
            "domain": [("snapshot_id", "=", self.id)],
        }
