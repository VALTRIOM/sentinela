from odoo import fields, models, api


class SentinellaCostLine(models.Model):
    _name = "sentinella.cost.line"
    _description = "Línea de Costo Sentinella"
    _order = "amount_current desc"

    cost_id = fields.Many2one("sentinella.cost", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="cost_id.company_id", store=True)
    currency_id = fields.Many2one(related="cost_id.currency_id", store=True)

    account_id = fields.Many2one("account.account")
    account_name = fields.Char("Cuenta")
    account_type_cat = fields.Selection([
        ("cogs", "COGS"),
        ("opex", "OPEX"),
        ("financial", "Financiero"),
        ("other", "Otro"),
    ], string="Categoría", default="opex")

    amount_current = fields.Monetary("Monto Actual", currency_field="currency_id")
    amount_prev = fields.Monetary("Monto Anterior", currency_field="currency_id")
    change_pct = fields.Float("Var %", digits=(5, 1))
    pct_of_revenue = fields.Float("% Ventas", digits=(5, 1))
    pct_of_total = fields.Float("% Gasto Total", digits=(5, 1))

    alert_state = fields.Selection([
        ("normal", "Normal"),
        ("anomalia", "Anomalía (>20% crecimiento)"),
        ("exceso", "Exceso (supera umbral)"),
    ], default="normal")


class SentinellaRecommendation(models.Model):
    _name = "sentinella.recommendation"
    _description = "Recomendación Sentinella"
    _inherit = ["mail.thread"]
    _order = "priority asc, date desc"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    cost_id = fields.Many2one("sentinella.cost", ondelete="set null")
    snapshot_id = fields.Many2one("sentinella.snapshot", ondelete="set null")
    date = fields.Date(default=fields.Date.today, index=True)

    category = fields.Selection([
        ("reduccion_costo", "Reducción de Costo"),
        ("aumento_ingreso", "Aumento de Ingresos"),
        ("liquidez", "Mejora de Liquidez"),
        ("riesgo_cliente", "Riesgo de Cliente"),
        ("riesgo_proveedor", "Riesgo de Proveedor"),
        ("alerta_operativa", "Alerta Operativa"),
    ], required=True)

    priority = fields.Selection([
        ("1", "Alta"),
        ("2", "Media"),
        ("3", "Baja"),
    ], default="2")

    title = fields.Char(required=True)
    body = fields.Html()
    impact = fields.Monetary("Impacto Estimado $", currency_field="currency_id")

    state = fields.Selection([
        ("abierta", "Abierta"),
        ("en_proceso", "En Proceso"),
        ("cerrada", "Cerrada"),
        ("descartada", "Descartada"),
    ], default="abierta", tracking=True)

    responsible_id = fields.Many2one("res.users", "Responsable")

    @api.model
    def generate_from_snapshot(self, snapshot):
        """Genera recomendaciones automáticas basadas en un snapshot de KPIs."""
        company = snapshot.company_id
        cfg = self.env["sentinella.config"].get_for_company(company.id)
        recs = []

        def add(cat, pri, title, body, impact=0.0):
            recs.append({
                "company_id": company.id,
                "snapshot_id": snapshot.id,
                "category": cat,
                "priority": pri,
                "title": title,
                "body": body,
                "impact": impact,
            })

        # Liquidez crítica
        if snapshot.quick_ratio < cfg.quick_ratio_critical:
            add("liquidez", "1",
                f"Quick Ratio crítico: {snapshot.quick_ratio:.2f}",
                f"<p>El Quick Ratio de <b>{snapshot.quick_ratio:.2f}</b> está por debajo del umbral crítico "
                f"de {cfg.quick_ratio_critical}. Considerar factoring de cartera o línea de crédito "
                f"de corto plazo para cubrir obligaciones inmediatas.</p>")

        # Días de caja bajos
        if snapshot.dias_caja < cfg.dias_caja_critical:
            add("liquidez", "1",
                f"Solo {snapshot.dias_caja:.0f} días de caja disponibles",
                f"<p>Con {snapshot.dias_caja:.0f} días de caja, la empresa podría no cubrir sus gastos "
                f"operativos en menos de 2 semanas. Prioridad: cobrar cartera vencida con descuento del "
                f"3-5% si es necesario, y congelar todo capex no crítico.</p>")

        # DSO alto → libera caja si mejora
        if snapshot.dso > cfg.dso_warning:
            cash_impact = snapshot.ar_balance * min((snapshot.dso - 45) / snapshot.dso, 0.3)
            add("aumento_ingreso", "1",
                f"Cobrar cartera más rápido libera ${cash_impact:,.0f}",
                f"<p>El DSO actual es de <b>{snapshot.dso:.0f} días</b>. Reducirlo a 45 días liberaría "
                f"aproximadamente <b>${cash_impact:,.0f}</b> en caja. Acciones: revisar aging de cartera, "
                f"ofrecer descuento por pronto pago del 2%, automatizar recordatorios de cobro.</p>",
                impact=cash_impact)

        # Inventario lento
        if snapshot.dio > 90:
            cash_impact = snapshot.inventory_value * 0.15
            add("liquidez", "2",
                f"Inventario lento ({snapshot.dio:.0f} días) — liquidar slow-movers",
                f"<p>El DIO de <b>{snapshot.dio:.0f} días</b> indica rotación lenta. Identificar SKUs "
                f"con más de 120 días sin movimiento y liquidarlos a costo para liberar "
                f"aproximadamente <b>${cash_impact:,.0f}</b>.</p>",
                impact=cash_impact)

        # Carga financiera excesiva
        if snapshot.revenue_ltm > 0:
            fin_pct = snapshot.financial_exp / snapshot.revenue_ltm * 100
            if fin_pct > 8:
                add("reduccion_costo", "1",
                    f"Carga financiera excesiva: {fin_pct:.1f}% de ventas",
                    f"<p>Los gastos financieros representan el <b>{fin_pct:.1f}%</b> de las ventas. "
                    f"Meta recomendada: <5%. Opciones: refinanciar deuda a menor tasa, prepagar "
                    f"préstamos de mayor costo, o negociar extensión de plazos.</p>",
                    impact=snapshot.financial_exp * 0.3)

        # CCC muy alto
        if snapshot.ccc > cfg.ccc_critical:
            add("liquidez", "2",
                f"Ciclo de Conversión de Efectivo de {snapshot.ccc:.0f} días es crítico",
                f"<p>El CCC de <b>{snapshot.ccc:.0f} días</b> significa que la empresa financia su ciclo "
                f"operativo durante 3+ meses. Reducir DSO y DIO, extender DPO con proveedores no críticos.</p>")

        # Altman Z' en zona de distress
        if snapshot.altman_z < cfg.altman_z_critical:
            add("alerta_operativa", "1",
                f"Altman Z' = {snapshot.altman_z:.2f} — Zona de Distress",
                f"<p>El score <b>Z' = {snapshot.altman_z:.2f}</b> indica alta probabilidad de dificultades "
                f"financieras. Se recomienda reunión inmediata con dirección para revisar el plan de "
                f"acción financiero y comunicar proactivamente a acreedores principales.</p>")
        elif snapshot.altman_z < cfg.altman_z_warning:
            add("alerta_operativa", "2",
                f"Altman Z' = {snapshot.altman_z:.2f} — Zona Gris",
                f"<p>El score <b>Z' = {snapshot.altman_z:.2f}</b> está en zona de precaución (1.23–2.9). "
                f"Monitorear de cerca y ejecutar acciones de mejora de liquidez y reducción de deuda.</p>")

        for vals in recs:
            # Evitar duplicados en el mismo día
            existing = self.search([
                ("company_id", "=", company.id),
                ("title", "=", vals["title"]),
                ("date", "=", vals.get("date", fields.Date.today())),
            ], limit=1)
            if not existing:
                self.create(vals)

    @api.model
    def generate_from_costs(self, cost):
        """Genera recomendaciones basadas en análisis de costos."""
        company = cost.company_id
        cfg = self.env["sentinella.config"].get_for_company(company.id)
        recs = []

        def add(cat, pri, title, body, impact=0.0):
            recs.append({
                "company_id": company.id,
                "cost_id": cost.id,
                "category": cat,
                "priority": pri,
                "title": title,
                "body": body,
                "impact": impact,
            })

        # OPEX excesivo
        if cost.opex_revenue_pct > cfg.opex_revenue_critical:
            add("reduccion_costo", "1",
                f"OPEX consume {cost.opex_revenue_pct:.1f}% de ventas — crítico",
                f"<p>Los gastos operativos representan <b>{cost.opex_revenue_pct:.1f}%</b> de las ventas "
                f"(meta: <30%). Revisar las 3 cuentas de mayor monto para identificar reducciones.</p>",
                impact=cost.total_opex * 0.10)

        # Crecimiento de OPEX supera crecimiento de ventas
        if cost.opex_change_pct > cost.revenue_change_pct + 10 and cost.opex_change_pct > 0:
            add("reduccion_costo", "2",
                f"Costos crecen {cost.opex_change_pct:.1f}% vs ventas {cost.revenue_change_pct:.1f}%",
                f"<p>Los gastos operativos crecieron <b>{cost.opex_change_pct:.1f}%</b> mientras las "
                f"ventas solo crecieron {cost.revenue_change_pct:.1f}%. El margen se está comprimiendo.</p>")

        # Cuentas con anomalías
        anomalies = cost.line_ids.filtered(lambda l: l.alert_state == "anomalia")
        for line in anomalies[:3]:
            add("reduccion_costo", "2",
                f"Gasto en '{line.account_name}' subió {line.change_pct:.0f}%",
                f"<p>La cuenta <b>{line.account_name}</b> aumentó <b>{line.change_pct:.0f}%</b> vs el "
                f"período anterior (${line.amount_prev:,.0f} → ${line.amount_current:,.0f}). "
                f"Revisar si el incremento es justificado.</p>",
                impact=line.amount_current - line.amount_prev)

        for vals in recs:
            existing = self.search([
                ("company_id", "=", company.id),
                ("title", "=", vals["title"]),
                ("date", "=", vals.get("date", fields.Date.today())),
            ], limit=1)
            if not existing:
                self.create(vals)
