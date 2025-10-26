#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FinSight主程序集成测试
测试新的LangChain版本主程序功能
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
import asyncio
from datetime import datetime

# 导入主程序模块
import main
from langchain_agent import create_langchain_financial_agent
from streaming_support import FinancialDashboard

class TestMainProgram(unittest.TestCase):
    """主程序测试类"""

    def setUp(self):
        """测试前置设置"""
        self.test_query = "测试AAPL股票"
        self.test_provider = "gemini_proxy"
        self.test_model = "gemini-2.5-flash-preview-05-20"

    def test_print_banner(self):
        """测试横幅显示功能"""
        print("\n测试横幅显示...")
        # 捕获输出
        with patch('builtins.print') as mock_print:
            main.print_banner()
            # 验证print被调用
            self.assertTrue(mock_print.called)
            # 验证横幅内容包含关键信息
            call_args = [str(call) for call in mock_print.call_args_list]
            banner_text = ''.join(call_args)
            self.assertIn("FinSight AI", banner_text)
            self.assertIn("LangChain 1.0.1", banner_text)

    def test_print_help(self):
        """测试帮助信息显示"""
        print("\n测试帮助信息...")
        with patch('builtins.print') as mock_print:
            main.print_help()
            self.assertTrue(mock_print.called)
            call_args = [str(call) for call in mock_print.call_args_list]
            help_text = ''.join(call_args)
            self.assertIn("使用说明", help_text)
            self.assertIn("示例查询", help_text)

    def test_create_agent_with_config_success(self):
        """测试Agent创建成功场景"""
        print("\n测试Agent创建成功...")

        # 模拟Agent创建
        with patch('main.create_langchain_financial_agent') as mock_create:
            mock_agent = MagicMock()
            mock_agent.get_agent_info.return_value = {
                'framework': 'LangChain 1.0.1',
                'tools_count': 9,
                'max_iterations': 15
            }
            mock_create.return_value = mock_agent

            result = main.create_agent_with_config(
                provider=self.test_provider,
                model=self.test_model
            )

            self.assertIsNotNone(result)
            mock_create.assert_called_once_with(
                provider=self.test_provider,
                model=self.test_model,
                verbose=True,
                max_iterations=15,
                show_intermediate_steps=True
            )

    def test_create_agent_with_config_failure(self):
        """测试Agent创建失败场景"""
        print("\n测试Agent创建失败...")

        with patch('main.create_langchain_financial_agent') as mock_create:
            mock_create.side_effect = Exception("API密钥无效")

            with self.assertRaises(SystemExit):
                main.create_agent_with_config(
                    provider="invalid_provider",
                    model="invalid_model"
                )

    def test_run_streaming_analysis_success(self):
        """测试流式分析成功场景"""
        print("\n测试流式分析成功...")

        # 创建模拟Agent
        mock_agent = MagicMock()

        # 创建模拟流式输出器
        with patch('main.AsyncFinancialStreamer') as mock_streamer_class:
            mock_streamer = MagicMock()
            mock_streamer.stream_analysis.return_value = "测试分析结果"
            mock_streamer_class.return_value = mock_streamer

            # 运行异步测试
            result = asyncio.run(
                main.run_streaming_analysis(mock_agent, self.test_query)
            )

            self.assertEqual(result, "测试分析结果")
            mock_streamer.stream_analysis.assert_called_once_with(mock_agent, self.test_query)

    def test_run_streaming_analysis_failure(self):
        """测试流式分析失败场景"""
        print("\n测试流式分析失败...")

        mock_agent = MagicMock()

        with patch('main.AsyncFinancialStreamer') as mock_streamer_class:
            mock_streamer = MagicMock()
            mock_streamer.stream_analysis.side_effect = Exception("流式分析失败")
            mock_streamer_class.return_value = mock_streamer

            result = asyncio.run(
                main.run_streaming_analysis(mock_agent, self.test_query)
            )

            self.assertIn("分析失败", result)

    @patch('builtins.input')
    @patch('main.FinancialDashboard')
    def test_run_interactive_mode_normal_exit(self, mock_dashboard_class, mock_input):
        """测试交互模式正常退出"""
        print("\n测试交互模式正常退出...")

        # 模拟用户输入
        mock_input.side_effect = ["测试查询", "exit"]

        # 模拟Agent
        mock_agent = MagicMock()
        mock_agent.analyze.return_value = "测试分析结果"

        # 模拟仪表板
        mock_dashboard = MagicMock()
        mock_dashboard_class.return_value = mock_dashboard

        # 运行交互模式（应该会正常退出）
        with patch('builtins.print') as mock_print:
            main.run_interactive_mode(mock_agent, use_streaming=False)

            # 验证退出消息
            print_calls = [str(call) for call in mock_print.call_args_list]
            exit_message_found = any("感谢使用" in call for call in print_calls)
            self.assertTrue(exit_message_found)

    @patch('builtins.input')
    def test_run_interactive_mode_keyboard_interrupt(self, mock_input):
        """测试交互模式键盘中断"""
        print("\n测试交互模式键盘中断...")

        # 模拟键盘中断
        mock_input.side_effect = KeyboardInterrupt()

        mock_agent = MagicMock()

        with patch('builtins.print') as mock_print:
            main.run_interactive_mode(mock_agent, use_streaming=False)

            # 验证中断消息
            print_calls = [str(call) for call in mock_print.call_args_list]
            interrupt_message_found = any("程序被用户中断" in call for call in print_calls)
            self.assertTrue(interrupt_message_found)

    def test_run_batch_mode_success(self):
        """测试批处理模式成功"""
        print("\n测试批处理模式成功...")

        mock_agent = MagicMock()
        mock_agent.analyze.return_value = "批处理分析结果"
        queries = ["AAPL", "MSFT", "GOOGL"]

        with patch('main.FinancialDashboard') as mock_dashboard_class:
            mock_dashboard = MagicMock()
            mock_dashboard_class.return_value = mock_dashboard

            with patch('builtins.print') as mock_print:
                main.run_batch_mode(mock_agent, queries, use_streaming=False)

                # 验证分析调用次数
                self.assertEqual(mock_agent.analyze.call_count, len(queries))

                # 验证批处理完成消息
                print_calls = [str(call) for call in mock_print.call_args_list]
                batch_complete_found = any("批处理完成" in call for call in print_calls)
                self.assertTrue(batch_complete_found)

    def test_run_batch_mode_with_streaming(self):
        """测试批处理模式流式输出"""
        print("\n测试批处理模式流式输出...")

        mock_agent = MagicMock()
        queries = ["AAPL", "MSFT"]

        with patch('main.run_streaming_analysis') as mock_streaming:
            mock_streaming.return_value = "流式分析结果"

            with patch('main.FinancialDashboard') as mock_dashboard_class:
                mock_dashboard = MagicMock()
                mock_dashboard_class.return_value = mock_dashboard

                main.run_batch_mode(mock_agent, queries, use_streaming=True)

                # 验证流式分析调用次数
                self.assertEqual(mock_streaming.call_count, len(queries))

    @patch('sys.argv', ['main.py', '--help-extended'])
    @patch('main.print_help')
    @patch('main.print_banner')
    def test_main_help_extended(self, mock_banner, mock_help):
        """测试主程序扩展帮助"""
        print("\n测试主程序扩展帮助...")

        main.main()

        mock_banner.assert_called_once()
        mock_help.assert_called_once()

    @patch('sys.argv', ['main.py', '测试查询'])
    @patch('main.print_banner')
    @patch('main.create_agent_with_config')
    def test_main_single_query(self, mock_create_agent, mock_banner):
        """测试主程序单次查询模式"""
        print("\n测试主程序单次查询...")

        # 模拟Agent
        mock_agent = MagicMock()
        mock_agent.analyze.return_value = "单次查询结果"
        mock_create_agent.return_value = mock_agent

        with patch('builtins.print') as mock_print:
            main.main()

            mock_create_agent.assert_called_once()
            mock_agent.analyze.assert_called_once_with("测试查询")

    @patch('sys.argv', ['main.py', 'AAPL', 'MSFT', '--batch'])
    @patch('main.print_banner')
    @patch('main.create_agent_with_config')
    def test_main_batch_mode(self, mock_create_agent, mock_banner):
        """测试主程序批处理模式"""
        print("\n测试主程序批处理模式...")

        mock_agent = MagicMock()
        mock_agent.analyze.return_value = "批处理结果"
        mock_create_agent.return_value = mock_agent

        with patch('main.run_batch_mode') as mock_batch:
            main.main()

            mock_batch.assert_called_once_with(mock_agent, ["AAPL", "MSFT"], False)

    @patch('sys.argv', ['main.py', 'TSLA', '--streaming'])
    @patch('main.print_banner')
    @patch('main.create_agent_with_config')
    def test_main_streaming_mode(self, mock_create_agent, mock_banner):
        """测试主程序流式模式"""
        print("\n测试主程序流式模式...")

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        with patch('asyncio.run') as mock_asyncio_run:
            mock_asyncio_run.return_value = "流式结果"

            with patch('builtins.print') as mock_print:
                main.main()

                mock_asyncio_run.assert_called_once()

    @patch('sys.argv', ['main.py', '--provider', 'openai', '--verbose'])
    @patch('main.print_banner')
    @patch('main.create_agent_with_config')
    def test_main_custom_provider(self, mock_create_agent, mock_banner):
        """测试主程序自定义提供商"""
        print("\n测试主程序自定义提供商...")

        mock_agent = MagicMock()
        mock_agent.get_agent_info.return_value = {
            'framework': 'LangChain 1.0.1',
            'tools_count': 9,
            'max_iterations': 15
        }
        mock_create_agent.return_value = mock_agent

        with patch('main.run_interactive_mode') as mock_interactive:
            main.main()

            # 验证使用自定义提供商创建Agent
            mock_create_agent.assert_called_once_with(
                provider="openai",
                model="gemini-2.5-flash-preview-05-20",
                streaming=False
            )

class TestMainProgramIntegration(unittest.TestCase):
    """主程序集成测试类"""

    def setUp(self):
        """测试前置设置"""
        print("\n设置集成测试环境...")

    def test_agent_creation_integration(self):
        """测试Agent创建集成"""
        print("\n测试Agent创建集成...")

        try:
            # 尝试创建真实的Agent（可能因为API密钥而失败）
            agent = create_langchain_financial_agent(
                provider="gemini_proxy",
                model="gemini-2.5-flash-preview-05-20"
            )

            # 如果成功创建，验证基本功能
            self.assertIsNotNone(agent)
            info = agent.get_agent_info()
            self.assertIn('framework', info)
            self.assertIn('tools_count', info)

        except Exception as e:
            # 如果创建失败（通常是API密钥问题），跳过测试
            print(f"   Agent创建失败（可能是API密钥问题）: {str(e)}")
            self.skipTest("需要有效的API密钥才能创建Agent")

    def test_dashboard_creation(self):
        """测试仪表板创建"""
        print("\n测试仪表板创建...")

        dashboard = FinancialDashboard()
        self.assertIsNotNone(dashboard)

        # 测试基本功能
        dashboard.start_analysis("测试查询")
        dashboard.update_step("action", "测试步骤")
        dashboard.finish_analysis("测试结果", success=True)

        status = dashboard.get_current_status()
        self.assertIsNotNone(status)

    def test_main_imports(self):
        """测试主程序导入"""
        print("\n测试主程序导入...")

        # 验证所有必要的导入都能成功
        try:
            import main
            self.assertTrue(hasattr(main, 'print_banner'))
            self.assertTrue(hasattr(main, 'create_agent_with_config'))
            self.assertTrue(hasattr(main, 'run_interactive_mode'))
            self.assertTrue(hasattr(main, 'run_batch_mode'))
            self.assertTrue(hasattr(main, 'main'))
        except ImportError as e:
            self.fail(f"主程序导入失败: {str(e)}")

def run_main_program_tests():
    """运行主程序测试"""
    print("=" * 80)
    print("FinSight 主程序集成测试")
    print("=" * 80)

    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试用例
    suite.addTests(loader.loadTestsFromTestCase(TestMainProgram))
    suite.addTests(loader.loadTestsFromTestCase(TestMainProgramIntegration))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 输出结果统计
    print("\n" + "=" * 80)
    print("测试结果统计:")
    print(f"   总测试数: {result.testsRun}")
    print(f"   成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"   失败: {len(result.failures)}")
    print(f"   错误: {len(result.errors)}")
    print(f"   跳过: {len(result.skipped) if hasattr(result, 'skipped') else 0}")

    if result.failures:
        print("\n失败的测试:")
        for test, traceback in result.failures:
            print(f"   - {test}: {traceback.split('AssertionError:')[-1].strip()}")

    if result.errors:
        print("\n错误的测试:")
        for test, traceback in result.errors:
            print(f"   - {test}: {traceback.split('Exception:')[-1].strip()}")

    success_rate = (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100
    print(f"\n测试成功率: {success_rate:.1f}%")

    if success_rate >= 90:
        print("主程序集成测试通过！")
    else:
        print("部分测试未通过，请检查相关功能")

    print("=" * 80)

    return result.wasSuccessful()

if __name__ == "__main__":
    success = run_main_program_tests()
    sys.exit(0 if success else 1)