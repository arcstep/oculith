import os
import pytest
import tempfile
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock, ANY

from oculith.file_utils import detect_file_type, is_image_file, convert_image_to_pdf
from oculith.common import prepare_file, is_base64
from oculith.convert import convert


# -----文件类型检测测试-----
def test_detect_file_type():
    """测试文件类型检测功能"""
    # 创建临时文件进行测试
    with tempfile.NamedTemporaryFile(suffix='.pdf') as pdf_file, \
         tempfile.NamedTemporaryFile(suffix='.jpg') as jpg_file, \
         tempfile.NamedTemporaryFile(suffix='.docx') as docx_file, \
         tempfile.NamedTemporaryFile(suffix='.txt') as txt_file:
        
        assert detect_file_type(pdf_file.name) == 'pdf'
        assert detect_file_type(jpg_file.name) == 'jpg'
        assert detect_file_type(docx_file.name) == 'docx'
        assert detect_file_type(txt_file.name) == 'txt'


def test_is_image_file():
    """测试图片文件检测"""
    assert is_image_file('jpg') is True
    assert is_image_file('jpeg') is True
    assert is_image_file('png') is True
    assert is_image_file('gif') is True
    assert is_image_file('pdf') is False
    assert is_image_file('docx') is False
    assert is_image_file('txt') is False


# -----图片转PDF测试-----
@patch('PIL.Image.open')
@patch('os.path.exists')  # 添加对os.path.exists的模拟
def test_convert_image_to_pdf(mock_exists, mock_open):
    """测试图片转PDF功能"""
    # 模拟PIL.Image操作
    mock_img = MagicMock()
    mock_img.mode = 'RGB'
    mock_img.save = MagicMock()
    mock_open.return_value = mock_img
    
    # 模拟文件存在检查
    mock_exists.return_value = True
    
    # 使用临时文件测试
    with tempfile.NamedTemporaryFile(suffix='.jpg') as jpg_file:
        pdf_path, is_temp = convert_image_to_pdf(jpg_file.name)
        
        # 检查是否调用了正确的方法
        mock_open.assert_called_once_with(jpg_file.name)
        mock_img.save.assert_called_once()
        assert pdf_path.endswith('.pdf')
        
        # 不需要检查真实文件，因为我们已经模拟了文件存在


# -----文件准备测试-----
@patch('oculith.common.detect_file_type')
def test_prepare_local_file(mock_detect):
    """测试本地文件准备逻辑"""
    mock_detect.return_value = 'pdf'
    
    with tempfile.NamedTemporaryFile(suffix='.pdf') as pdf_file:
        path, is_temp, detected_type, _ = prepare_file(pdf_file.name, 'file', '')
        
        assert path == os.path.abspath(pdf_file.name)
        assert is_temp is False
        assert detected_type == 'pdf'


@patch('oculith.common.detect_file_type')
@patch('oculith.common.is_image_file')
@patch('oculith.common.convert_image_to_pdf')  # 直接模拟这个函数，而不是其调用的函数
def test_prepare_local_image(mock_convert_image, mock_is_image, mock_detect):
    """测试本地图片自动转PDF"""
    mock_detect.return_value = 'jpg'
    mock_is_image.return_value = True
    mock_convert_image.return_value = ('/tmp/converted.pdf', True)
    
    with tempfile.NamedTemporaryFile(suffix='.jpg') as jpg_file:
        path, is_temp, detected_type, _ = prepare_file(jpg_file.name, 'file', '')
        
        # 检查正确的函数被调用
        assert path == '/tmp/converted.pdf'
        assert is_temp is True
        assert detected_type == 'pdf'
        mock_convert_image.assert_called_once_with(os.path.abspath(jpg_file.name))


@patch('requests.get')
@patch('oculith.common.detect_file_type')
def test_prepare_url_file(mock_detect, mock_get):
    """测试URL文件准备逻辑"""
    mock_detect.return_value = 'pdf'
    
    # 模拟请求响应
    mock_response = MagicMock()
    mock_response.iter_content.return_value = [b'test data']
    mock_get.return_value = mock_response
    
    path, is_temp, detected_type, _ = prepare_file('https://example.com/test.pdf', 'url', '')
    
    assert path is not None
    assert is_temp is True
    assert detected_type == 'pdf'
    

@patch('oculith.common.is_base64')
def test_prepare_base64_file(mock_is_base64):
    """测试Base64文件准备逻辑"""
    mock_is_base64.return_value = True
    
    # 创建简单的base64编码
    content = base64.b64encode(b'test pdf content').decode('utf-8')
    
    with patch('oculith.common.detect_file_type', return_value='pdf'):
        path, is_temp, detected_type, _ = prepare_file(content, 'base64', 'pdf')
        
        assert path is not None
        assert is_temp is True
        assert detected_type == 'pdf'
        
        # 清理
        if os.path.exists(path):
            os.unlink(path)


# -----Pipeline选择测试-----
@patch('oculith.convert.prepare_file')
@patch('oculith.convert.get_pdf_converter')
def test_pdf_pipeline_selection(mock_pdf_converter, mock_prepare):
    """测试PDF文件的pipeline选择逻辑"""
    # 模拟prepare_file返回PDF文件
    mock_prepare.return_value = ('/tmp/test.pdf', False, 'pdf', False)
    
    # 模拟converter
    mock_converter = MagicMock()
    mock_result = MagicMock()
    mock_result.document = MagicMock()
    mock_result.document.export_to_markdown.return_value = "mock markdown content"
    mock_converter.convert.return_value = mock_result
    mock_pdf_converter.return_value = mock_converter
    
    # 测试standard pipeline
    result = convert('content', 'file', 'pdf', pipeline='standard')
    mock_pdf_converter.assert_called_once()
    mock_converter.convert.assert_called_once()
    assert result['model_info']['pipeline'] == 'standard'
    
    # 重置mock
    mock_pdf_converter.reset_mock()
    mock_converter.convert.reset_mock()
    
    # 测试simple pipeline - 使用get_fast_pdf_converter
    with patch('oculith.convert.get_fast_pdf_converter') as mock_fast_pdf:
        mock_fast_result = MagicMock()
        mock_fast_result.text = "fast pdf content"
        mock_fast_result.input = MagicMock()
        mock_fast_result.input.file = "/tmp/test.pdf"
        mock_fast_pdf.return_value = mock_fast_result
        
        result = convert('content', 'file', 'pdf', pipeline='simple')
        mock_fast_pdf.assert_called_once_with('/tmp/test.pdf')
        assert result['model_info']['pipeline'] == 'simple_pdf'
    
    # 重置mock
    mock_pdf_converter.reset_mock()
    mock_converter.convert.reset_mock()
    
    # 测试vlm pipeline
    with patch('oculith.convert.get_vlm_converter') as mock_vlm:
        mock_vlm_converter = MagicMock()
        mock_vlm_result = MagicMock()
        mock_vlm_result.document = MagicMock()
        mock_vlm_result.document.export_to_markdown.return_value = "vlm markdown content" 
        mock_vlm_converter.convert.return_value = mock_vlm_result
        mock_vlm.return_value = mock_vlm_converter
        
        result = convert('content', 'file', 'pdf', pipeline='vlm')
        mock_vlm.assert_called_once()
        mock_vlm_converter.convert.assert_called_once()
        assert result['model_info']['pipeline'] == 'vlm'


@patch('oculith.convert.prepare_file')
@patch('oculith.convert.get_pdf_converter')
def test_image_pipeline_selection(mock_pdf_converter, mock_prepare):
    """测试图片文件的pipeline选择和自动转PDF"""
    # 模拟prepare_file返回图片已转换为PDF
    mock_prepare.return_value = ('/tmp/converted.pdf', True, 'pdf', True)
    
    # 模拟converter
    mock_converter = MagicMock()
    mock_result = MagicMock()
    mock_result.document = MagicMock()
    mock_result.document.export_to_markdown.return_value = "image converted to pdf content"
    mock_converter.convert.return_value = mock_result
    mock_pdf_converter.return_value = mock_converter
    
    # 测试auto pipeline (应该选择standard)
    result = convert('content', 'file', 'jpg', pipeline='auto')
    mock_pdf_converter.assert_called_once()
    mock_converter.convert.assert_called_once()
    assert result['model_info']['pipeline'] == 'standard'


@patch('oculith.convert.prepare_file')
@patch('oculith.convert.get_simple_converter')
@patch('oculith.convert.get_pdf_converter')  # 添加这个模拟
def test_other_formats_pipeline_selection(mock_pdf_converter, mock_simple_converter, mock_prepare):
    """测试其他格式文件的pipeline选择逻辑"""
    # 模拟prepare_file返回docx文件
    mock_prepare.return_value = ('/tmp/test.docx', False, 'docx', False)
    
    # 模拟simple converter
    mock_simple_converter_instance = MagicMock()
    mock_simple_result = MagicMock()
    mock_simple_result.document = MagicMock()
    mock_simple_result.document.export_to_markdown.return_value = "docx markdown content"
    mock_simple_converter_instance.convert.return_value = mock_simple_result
    mock_simple_converter.return_value = mock_simple_converter_instance
    
    # 模拟PDF converter (用于auto模式)
    mock_pdf_converter_instance = MagicMock()
    mock_pdf_result = MagicMock()
    mock_pdf_result.document = MagicMock()
    mock_pdf_result.document.export_to_markdown.return_value = "pdf converter content"
    mock_pdf_converter_instance.convert.return_value = mock_pdf_result
    mock_pdf_converter.return_value = mock_pdf_converter_instance
    
    # 测试simple pipeline
    result = convert('content', 'file', 'docx', pipeline='simple')
    mock_simple_converter.assert_called_once()
    assert mock_simple_converter_instance.convert.call_count == 2
    assert result['model_info']['pipeline'] == 'simple'
    
    # 重置所有mock
    mock_simple_converter.reset_mock()
    mock_simple_converter_instance.reset_mock()
    mock_simple_converter_instance.convert.reset_mock()
    mock_pdf_converter.reset_mock()
    mock_pdf_converter_instance.reset_mock()
    mock_pdf_converter_instance.convert.reset_mock()
    
    # 测试auto pipeline (实际上会使用PDF转换器)
    result = convert('content', 'file', 'docx', pipeline='auto')
    mock_pdf_converter.assert_called_once()  # 期望调用PDF转换器
    assert mock_pdf_converter_instance.convert.call_count >= 1
    assert result['model_info']['pipeline'] == 'standard'  # 实际pipeline是standard
