import asyncio
import os
import logging
from typing import TypedDict

from langgraph.constants import START, END
from langgraph.graph import StateGraph

import agents
import bitbucket

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    pr_url: str
    auth: dict
    diff: str
    report: str


def connect_bitbucket(state: AgentState) -> dict:
    logger.info("Node: connect_bitbucket")
    auth = bitbucket.connect()
    return {"auth": auth}


def fetch_diff(state: AgentState) -> dict:
    logger.info("Node: fetch_diff")
    diff = bitbucket.fetch_diff(state["pr_url"], state["auth"])
    return {"diff": diff}


def run_cli(state: AgentState) -> dict:
    logger.info("Node: run_cli")
    cli = os.getenv("CLI", "claude")
    result = asyncio.run(agents.run_review(state["diff"], cli))
    return {"report": result}


workflow = StateGraph(AgentState)

workflow.add_node("connect_bitbucket", connect_bitbucket)
workflow.add_node("fetch_diff", fetch_diff)
workflow.add_node("run_cli", run_cli)

workflow.add_edge(START, "connect_bitbucket")
workflow.add_edge("connect_bitbucket", "fetch_diff")
workflow.add_edge("fetch_diff", "run_cli")
workflow.add_edge("run_cli", END)

app = workflow.compile()
