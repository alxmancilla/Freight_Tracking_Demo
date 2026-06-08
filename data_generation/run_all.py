"""Run all generators in the correct order."""
from data_generation import (
    generate_geofences, generate_shipments, generate_tracking_events, generate_agent_memory,
)


def main() -> None:
    print("==> 1/4 Geofences");        generate_geofences.main()
    print("==> 2/4 Shipments");        generate_shipments.main()
    print("==> 3/4 Tracking events");  generate_tracking_events.main()
    print("==> 4/4 Agent memory");     generate_agent_memory.main()
    print("\nAll generators complete.")


if __name__ == "__main__":
    main()
