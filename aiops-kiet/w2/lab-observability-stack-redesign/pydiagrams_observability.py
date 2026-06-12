from pydiagrams.Views import ViewContext
from pydiagrams.helpers.Graphviz import Helper


def main():
    Helper.generate_diagram = staticmethod(lambda source_file: print(f"Graphviz source written to {source_file}"))

    with ViewContext(Helper, filename="observability-stack", label="GeekShop Observability Redesign") as d:
        d.node_attrs = {"width": "1.8"}
        d.edge_attrs = {"fontsize": "11"}

        with d.Cluster("GeekShop Kubernetes", fillcolor="#e8f5e9"):
            checkout = d.System("checkout-service", fillcolor="#c8e6c9")
            cart = d.System("cart-service", fillcolor="#c8e6c9")
            payment = d.System("payment-service", fillcolor="#c8e6c9")
            order = d.System("order-service", fillcolor="#c8e6c9")
            inventory = d.System("inventory-service", fillcolor="#c8e6c9")
            catalog = d.System("catalog-service", fillcolor="#c8e6c9")
            auth = d.System("auth-service", fillcolor="#c8e6c9")
            search = d.System("search-service", fillcolor="#c8e6c9")
            shipping = d.System("shipping-service", fillcolor="#c8e6c9")
            notification = d.System("notification-service", fillcolor="#c8e6c9")

            collector = d.Task("OTel Collector\nDaemonSet", fillcolor="#fff3e0")
            tail = d.Task("Tail-Based\nSampling", fillcolor="#fff3e0")
            filtering = d.Task("Edge Label\nFiltering", fillcolor="#fff3e0")

            for svc in [checkout, cart, payment, order, inventory, catalog, auth, search, shipping, notification]:
                svc >> collector
            collector >> tail
            tail >> filtering

        with d.Cluster("Grafana SaaS", fillcolor="#e3f2fd"):
            mimir = d.System("Mimir\nMetrics", fillcolor="#bbdefb")
            loki = d.System("Loki\nLogs", fillcolor="#bbdefb")
            tempo = d.System("Tempo\nTraces", fillcolor="#bbdefb")
            grafana = d.System("Grafana\nUnified UI", fillcolor="#bbdefb")
            alertmanager = d.System("Alertmanager", fillcolor="#bbdefb")
            pagerduty = d.System("PagerDuty\nBusiness", fillcolor="#f3e5f5")
            slack = d.System("Slack", fillcolor="#f3e5f5")

            filtering >> mimir
            filtering >> loki
            filtering >> tempo
            mimir >> grafana
            loki >> grafana
            tempo >> grafana
            mimir >> alertmanager
            loki >> alertmanager
            tempo >> alertmanager
            alertmanager >> pagerduty % "dedup + route"
            alertmanager >> slack % "notify"

        with d.Cluster("Cold Storage", fillcolor="#fff8e1"):
            s3 = d.System("S3 Archive\n30+ days", fillcolor="#ffe0b2")
            mimir >> s3 % "cold retention"
            loki >> s3 % "cold retention"
            tempo >> s3 % "cold retention"


if __name__ == "__main__":
    main()
