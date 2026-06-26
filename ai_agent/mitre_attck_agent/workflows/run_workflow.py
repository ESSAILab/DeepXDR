import asyncio
import logging

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from mitre_attck_agent.workflows.state import create_initial_state
from mitre_attck_agent.workflows.graph import (
    create_graph_no_checkpointing,
    run_investigation,
)

import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

def quiet_dependency_logs():
    logging.getLogger().setLevel(logging.WARNING)

    # clean dependency noise
    for name in [
        "anyio",
        "asyncio",
        "httpx",
    ]:
        logging.getLogger(name).setLevel(logging.WARNING)


DEFAULT_INCIDENT = (
    "EDR alert: WINWORD.EXE spawned powershell.exe with an encoded command. "
    "Shortly after, rundll32.exe executed with a suspicious DLL entrypoint and "
    "a scheduled task was created for persistence. Network connections to an "
    "unfamiliar external IP followed."
)


async def main():
    """Run a basic investigation workflow."""
    quiet_dependency_logs()
    logger.info("\n" + "="*80)
    logger.info("MITRE ATT&CK Investigation Workflow - Basic Execution")
    logger.info("="*80 + "\n")

    try:
        # Create graph
        logger.info("Building workflow graph...")
        graph = create_graph_no_checkpointing()

        logger.info("Creating initial state...")
        initial_state = create_initial_state(
            incident_text=DEFAULT_INCIDENT,
            domain="enterprise",
            llm_model="deepseek-v3-2-251201",
        )

        # Run investigation
        logger.info("🚀 Starting investigation...\n")
        final_state = await run_investigation(graph, initial_state)

        # Print results
        logger.info("\n" + "="*80)
        logger.info("INVESTIGATION COMPLETE")
        logger.info("="*80)

        completed = final_state.get("completed_agents", [])
        logger.info(f"\nCompleted ({len(completed)}) agents:")
        for agent in completed:
            logger.info(f"   - {agent}")

        errors = final_state.get("errors", [])
        if errors:
            logger.error(f"\n Errors encountered ({len(errors)}):")
            for error in errors:
                logger.error(f" - {error.get('agent')}: {error.get('error')}")

        timings = final_state.get("timings", {})
        if timings:
            total_time = sum(timings.values())
            logger.info(f"\n Total time: {total_time:.2f}s")
            logger.info("\n  Agent timings:")
            for agent, duration in sorted(timings.items(), key=lambda x: x[1], reverse=True):
                percentage = (duration / total_time * 100) if total_time > 0 else 0
                logger.info(f"   {agent:25s}: {duration:6.2f}s ({percentage:5.1f}%)")

        logger.info("\nResults:")
        logger.info(f"Confirmed techniques: {len(final_state.get('confirmed_techniques', []))}")
        logger.info(f"Intel items: {len(final_state.get('intel', {}).get('intel', []))}")
        logger.info(f"Detection items: {len(final_state.get('detections', {}).get('detections', []))}")
        logger.info(f"Mitigation items: {len(final_state.get('mitigations', {}).get('mitigations', []))}")

        logger.info("\nReport: ./out/incident_report.md")

        logger.info("\n" + "="*80 + "\n")

        return final_state

    except Exception as e:
        logger.error(f"\n Investigation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


if __name__ == "__main__":
    asyncio.run(main())
