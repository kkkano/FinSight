#!/usr/bin/env python3
"""
PDF 导出服务
用于导出对话记录和图表到 PDF
"""

import logging

logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-


from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
import io

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    logger.info("⚠️  reportlab 未安装，PDF 导出功能将不可用。运行: pip install reportlab")


class PDFExportService:
    """PDF 导出服务"""
    
    def __init__(self):
        if not REPORTLAB_AVAILABLE:
            raise ImportError("reportlab 未安装，无法使用 PDF 导出功能")
        
        # 注册中文字体（解决乱码问题）
        self._register_chinese_fonts()
        
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _register_chinese_fonts(self):
        """注册中文字体支持"""
        try:
            import platform
            import os
            
            # 尝试注册系统中文字体
            system = platform.system()
            font_paths = []
            
            if system == "Windows":
                # Windows 系统字体路径
                font_paths = [
                    "C:/Windows/Fonts/simsun.ttc",  # 宋体
                    "C:/Windows/Fonts/simhei.ttf",  # 黑体
                    "C:/Windows/Fonts/msyh.ttc",   # 微软雅黑
                    "C:/Windows/Fonts/msyhbd.ttc", # 微软雅黑 Bold
                ]
            elif system == "Darwin":  # macOS
                font_paths = [
                    "/System/Library/Fonts/PingFang.ttc",
                    "/System/Library/Fonts/STHeiti Light.ttc",
                ]
            elif system == "Linux":
                font_paths = [
                    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                    "/usr/share/fonts/truetype/arphic/uming.ttc",
                ]
            
            # 尝试注册第一个可用的字体
            font_registered = False
            for font_path in font_paths:
                if os.path.exists(font_path):
                    try:
                        if font_path.endswith('.ttc'):
                            # TTC 字体需要指定子字体索引
                            pdfmetrics.registerFont(TTFont('ChineseFont', font_path, subfontIndex=0))
                        else:
                            pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
                        logger.info(f"[PDF] 成功注册中文字体: {font_path}")
                        font_registered = True
                        break
                    except Exception as e:
                        logger.info(f"[PDF] 注册字体失败 {font_path}: {e}")
                        continue
            
            if not font_registered:
                logger.info("[PDF] 警告: 未找到中文字体，PDF 中的中文可能显示为方块")
                # 使用默认字体（可能不支持中文）
                self.chinese_font = 'Helvetica'
            else:
                self.chinese_font = 'ChineseFont'
                
        except Exception as e:
            logger.info(f"[PDF] 字体注册过程出错: {e}")
            self.chinese_font = 'Helvetica'  # 回退到默认字体
    
    def _setup_custom_styles(self):
        """设置自定义样式"""
        # 标题样式
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontName=getattr(self, 'chinese_font', 'Helvetica'),
            fontSize=24,
            textColor=colors.HexColor('#2196F3'),
            spaceAfter=30,
            alignment=TA_CENTER
        ))
        
        # 副标题样式
        self.styles.add(ParagraphStyle(
            name='CustomHeading',
            parent=self.styles['Heading2'],
            fontName=getattr(self, 'chinese_font', 'Helvetica'),
            fontSize=16,
            textColor=colors.HexColor('#4CAF50'),
            spaceAfter=12,
            spaceBefore=12
        ))
        
        # 用户消息样式
        self.styles.add(ParagraphStyle(
            name='UserMessage',
            parent=self.styles['Normal'],
            fontName=getattr(self, 'chinese_font', 'Helvetica'),
            fontSize=11,
            textColor=colors.HexColor('#333333'),
            leftIndent=20,
            rightIndent=20,
            backColor=colors.HexColor('#E3F2FD'),
            borderPadding=10,
            spaceAfter=10
        ))
        
        # AI 消息样式
        self.styles.add(ParagraphStyle(
            name='AIMessage',
            parent=self.styles['Normal'],
            fontName=getattr(self, 'chinese_font', 'Helvetica'),
            fontSize=11,
            textColor=colors.HexColor('#333333'),
            leftIndent=20,
            rightIndent=20,
            backColor=colors.HexColor('#F1F8E9'),
            borderPadding=10,
            spaceAfter=10
        ))
        
        # 更新 Normal 样式以支持中文
        if hasattr(self, 'chinese_font'):
            self.styles['Normal'].fontName = self.chinese_font
    
    def export_conversation(
        self,
        messages: List[Dict],
        output_path: Optional[str] = None,
        title: str = "FinSight 对话记录"
    ) -> bytes:
        """
        导出对话记录到 PDF
        
        Args:
            messages: 消息列表，每个消息包含 'role', 'content', 'timestamp' 等字段
            output_path: 输出文件路径（如果为 None，返回 bytes）
            title: PDF 标题
            
        Returns:
            PDF 文件的 bytes（如果 output_path 为 None）
        """
        if output_path:
            buffer = None
            doc = SimpleDocTemplate(output_path, pagesize=A4)
        else:
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
        
        story = []
        
        # 标题
        story.append(Paragraph(title, self.styles['CustomTitle']))
        story.append(Spacer(1, 0.2*inch))
        
        # 导出时间
        export_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        story.append(Paragraph(f"导出时间: {export_time}", self.styles['Normal']))
        story.append(Spacer(1, 0.3*inch))
        
        # 对话内容
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')
            
            # 角色标签
            if role == 'user':
                role_label = "用户"
                style = self.styles['UserMessage']
            elif role == 'assistant':
                role_label = "AI 助手"
                style = self.styles['AIMessage']
            else:
                role_label = role
                style = self.styles['Normal']
            
            # 消息头部
            header = f"<b>{role_label}</b>"
            if timestamp:
                header += f" <i>({timestamp})</i>"
            story.append(Paragraph(header, self.styles['Normal']))
            story.append(Spacer(1, 0.1*inch))
            
            # 消息内容（处理换行和特殊字符）
            content_escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            content_escaped = content_escaped.replace('\n', '<br/>')
            
            story.append(Paragraph(content_escaped, style))
            story.append(Spacer(1, 0.2*inch))
            
            # 如果不是最后一条消息，添加分隔线
            if i < len(messages) - 1:
                story.append(Spacer(1, 0.1*inch))
        
        # 生成 PDF
        doc.build(story)
        
        if buffer:
            return buffer.getvalue()
        return None
    
    def export_with_charts(
        self,
        messages: List[Dict],
        charts: List[Dict],
        output_path: Optional[str] = None,
        title: str = "FinSight 对话记录（含图表）"
    ) -> bytes:
        """
        导出对话记录和图表到 PDF
        
        Args:
            messages: 消息列表
            charts: 图表列表，每个图表包含 'ticker', 'chart_type', 'image_path' 等字段
            output_path: 输出文件路径
            title: PDF 标题
            
        Returns:
            PDF 文件的 bytes
        """
        if output_path:
            buffer = None
            doc = SimpleDocTemplate(output_path, pagesize=A4)
        else:
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
        
        story = []
        
        # 标题
        story.append(Paragraph(title, self.styles['CustomTitle']))
        story.append(Spacer(1, 0.2*inch))
        
        # 导出时间
        export_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        story.append(Paragraph(f"导出时间: {export_time}", self.styles['Normal']))
        story.append(Spacer(1, 0.3*inch))
        
        # 对话内容
        for msg in messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')
            
            if role == 'user':
                role_label = "用户"
                style = self.styles['UserMessage']
            elif role == 'assistant':
                role_label = "AI 助手"
                style = self.styles['AIMessage']
            else:
                role_label = role
                style = self.styles['Normal']
            
            header = f"<b>{role_label}</b>"
            if timestamp:
                header += f" <i>({timestamp})</i>"
            story.append(Paragraph(header, self.styles['Normal']))
            story.append(Spacer(1, 0.1*inch))
            
            content_escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            content_escaped = content_escaped.replace('\n', '<br/>')
            story.append(Paragraph(content_escaped, style))
            story.append(Spacer(1, 0.2*inch))
        
        # 图表部分
        if charts:
            story.append(PageBreak())
            story.append(Paragraph("图表", self.styles['CustomHeading']))
            story.append(Spacer(1, 0.2*inch))
            
            for chart in charts:
                ticker = chart.get('ticker', 'Unknown')
                chart_type = chart.get('chart_type', 'Unknown')
                
                story.append(Paragraph(f"<b>{ticker} - {chart_type}</b>", self.styles['Normal']))
                story.append(Spacer(1, 0.1*inch))
                
                # 如果有图片路径，尝试添加图片
                image_path = chart.get('image_path')
                if image_path and Path(image_path).exists():
                    try:
                        img = Image(image_path, width=6*inch, height=4*inch)
                        story.append(img)
                    except Exception as e:
                        story.append(Paragraph(f"[图表图片加载失败: {e}]", self.styles['Normal']))
                else:
                    story.append(Paragraph("[图表数据]", self.styles['Normal']))
                
                story.append(Spacer(1, 0.3*inch))
        
        # 生成 PDF
        doc.build(story)
        
        if buffer:
            return buffer.getvalue()
        return None


def get_pdf_service() -> Optional[PDFExportService]:
    """获取 PDF 导出服务实例"""
    if not REPORTLAB_AVAILABLE:
        return None
    return PDFExportService()