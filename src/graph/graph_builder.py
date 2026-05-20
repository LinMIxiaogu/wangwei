"""
图构建器模块
"""
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.graph.node.node import status_router_node, \
    key_frame_filter_node, asr_node, vlm_choose_node, key_frame_detect_node, \
    text_and_image_combine_node, generate_node, xhs_note_scoring_node, xhs_note_publish_node, \
    collage_node, image_processing_node, xhs_final_text_node
from src.graph.node.node_by_poi_extract import poi_extract_node
from src.graph.node.node_by_xhs_cover import xhs_cover_opt_node
from src.graph.node.node_by_xhs_style import xhs_style_node
from src.graph.node.xhs_note_text_node import xhs_hot_content_node
from src.graph.state.types import State


def create_workflow() -> CompiledStateGraph:
    """创建多节点工作流"""
    workflow = StateGraph(State)

    # ========== 添加节点 ==========
    workflow.add_node("status_router", status_router_node)
    workflow.add_node("key_frame_filter_node", key_frame_filter_node)
    workflow.add_node("vlm_choose", vlm_choose_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("asr_node", asr_node)
    workflow.add_node("key_frame_detect_node", key_frame_detect_node)
    workflow.add_node("text_and_image_combine_node", text_and_image_combine_node)
    workflow.add_node("xhs_note_scoring_node", xhs_note_scoring_node)
    workflow.add_node("xhs_note_publish_node", xhs_note_publish_node)
    workflow.add_node("collage_node", collage_node)
    workflow.add_node("image_processing_node", image_processing_node)
    workflow.add_node("xhs_final_text_node", xhs_final_text_node)
    workflow.add_node("xhs_cover_opt_node", xhs_cover_opt_node)
    workflow.add_node("poi_extract_node", poi_extract_node)
    workflow.add_node("xhs_style_node", xhs_style_node)
    workflow.add_node("xhs_hot_content_node", xhs_hot_content_node)

    # ========== 构建边 ==========
    # 设置图的执行起点
    workflow.set_entry_point("status_router")

    compiled: CompiledStateGraph = workflow.compile()
    print("compiled.get_graph.draw_mermaid:\n" + compiled.get_graph().draw_mermaid())
    return compiled
