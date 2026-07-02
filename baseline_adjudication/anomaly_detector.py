import os
import json
import time
import hashlib
import logging
import threading  # 用于定时保存基线
from datetime import datetime
from dotenv import load_dotenv
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
import redis
from redis.exceptions import RedisError

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if os.getenv('DEBUG', 'False').lower() == 'true' else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger('anomaly_detector')
# 限制第三方库日志级别
logging.getLogger('kafka').setLevel(logging.WARNING)
logging.getLogger('redis').setLevel(logging.WARNING)

def safe_json_deserializer(m):
    """安全反序列化Kafka消息，非JSON或空消息返回None"""
    if not m or not m.strip():
        return None
    try:
        return json.loads(m.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning(f'收到非JSON格式消息，已跳过: {m[:100]}')
        return None


class AnomalyDetector:
    def __init__(self):
        # Kafka配置
        self.kafka_bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
        self.source_topic = os.getenv('KAFKA_SOURCE_TOPIC', 'event-source')
        self.agent_topic = os.getenv('KAFKA_AGENT_TOPIC', 'agent')
        self.agent_session_topic = os.getenv('KAFKA_AGENT_SESSION_TOPIC', 'agent.session.finished')
        
        # Kafka SASL认证配置
        self.kafka_security_protocol = os.getenv('KAFKA_SECURITY_PROTOCOL', 'PLAINTEXT')
        self.kafka_sasl_mechanism = os.getenv('KAFKA_SASL_MECHANISM', 'PLAIN')
        self.kafka_sasl_username = os.getenv('KAFKA_SASL_USERNAME', '')
        self.kafka_sasl_password = os.getenv('KAFKA_SASL_PASSWORD', '')
        
        # 记录Kafka安全配置（隐藏密码）
        if self.kafka_security_protocol != 'PLAINTEXT':
            logger.info(f'配置Kafka安全协议: {self.kafka_security_protocol}, 认证机制: {self.kafka_sasl_mechanism}, 用户名: {self.kafka_sasl_username}')
        else:
            logger.info('使用PLAINTEXT协议连接Kafka，无认证配置')
        
        # Redis配置
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis_db = int(os.getenv('REDIS_DB', 0))
        
        # 基线持久化配置
        self.baseline_file_path = os.getenv('BASELINE_FILE_PATH', 'baseline.json')
        #key_fields or timestamp
        self.redis_value_type = os.getenv('REDIS_VALUE_TYPE', 'key_fields')
        
        # 基线构建配置
        self.baseline_duration = int(os.getenv('BASELINE_DURATION', 300))  # 默认为5分钟
        self.baseline_start_time = time.time()
        self.is_baseline_phase = True
        
        # 持续构建基线配置
        self.continuous_baseline_enabled = os.getenv('CONTINUOUS_BASELINE_ENABLED', 'false').lower() == 'true'
        self.baseline_save_interval = int(os.getenv('BASELINE_SAVE_INTERVAL', 600))  # 默认10分钟
        self.last_baseline_save_time = time.time()
        self.baseline_modified = False  # 跟踪基线是否有更新
        self.save_timer = None  # 定时器
        self.running = False  # 运行状态
        logger.info(f"持续构建基线模式: {'开启' if self.continuous_baseline_enabled else '关闭'}")

        self.record_anomal_enabled = os.getenv('RECORD_ANOMAL_ENABLED', 'true').lower() == 'true' #默认开启记录异常事件
        self.anomal_save_interval = int(os.getenv('ANOMAL_SAVE_INTERVAL', 180))  # 默认3分钟
        self.anomaly_file_path = os.getenv('ANOMALY_FILE_PATH', 'anomalies.json')
        self.last_anomal_save_time = time.time()
        self.anomalies_modified = False  # 跟踪是否有异常事件
        self.anomal_save_timer = None  # 定时器
        self.anomalies = {}  # 在内存中存储异常数据
        if self.continuous_baseline_enabled and self.record_anomal_enabled:
            self.record_anomal_enabled = False
            logger.info(f"异常记录模式关闭，因为持续构建基线模式已开启")
        
        # 初始化客户端
        self.consumer = None
        self.producer = None
        self.redis_client = None
        
        # 关键字段配置 - 根据需求筛选稳定字段
        self.falco_key_fields = [
            # falco syscall事件字段
            {'output_fields': ['proc.name', 'proc.cmdline', 'fd.name', 'evt.type', 'evt.arg.flags','proc.exepath','proc.pname','proc.tty','user.name']},
            'rule', 'source','tags'
        ]
        
        # 根据attack_type动态配置rasp关键字段
        self.rasp_key_fields_config = {
            # 'readFile': None,  # readFile直接忽略，不提取任何字段
            'writeFile': ['attack_type', 'request_method', 'event_type', {'attack_params': ['realpath']}],
            'default': ['attack_type', 'request_method', 'event_type', 'attack_params']  # 默认包含attack_params
        }
        
        # 是否开启线程名称的模糊匹配,默认开启
        self.enable_thread_name_fuzzy_match = os.getenv('ENABLE_THREAD_NAME_FUZZY_MATCH', 'true').lower() == 'true' 

        # 是否开启文件路径的数字模糊匹配,星号的数量和数字一一对应,默认关闭
        # 例如：/srv/dotserver/tomcat-9.0.41/temp/nativelib-loader_1482855826203628338 模糊为 /srv/dotserver/tomcat-*.*.**/temp/nativelib-loader_*******************
        self.enable_filepath_num_fuzzy_match = os.getenv('ENABLE_FILEPATH_NUM_FUZZY_MATCH', 'false').lower() == 'true'
        
    def initialize_clients(self):
        """初始化Kafka和Redis客户端"""
        try:
            # 构建Kafka基础配置
            kafka_base_config = {
                'bootstrap_servers': self.kafka_bootstrap_servers.split(','),
                'security_protocol': self.kafka_security_protocol,
            }
            
            # 如果启用了SASL认证，添加相关配置
            if self.kafka_security_protocol in ['SASL_PLAINTEXT', 'PLAINTEXT']:
                kafka_base_config.update({
                    'sasl_mechanism': self.kafka_sasl_mechanism,
                    'sasl_plain_username': self.kafka_sasl_username,
                    'sasl_plain_password': self.kafka_sasl_password,
                })
                logger.debug(f'启用Kafka SASL认证，机制: {self.kafka_sasl_mechanism}, 用户名: {self.kafka_sasl_username}')
            
            # 初始化Kafka消费者
            consumer_config = {
                **kafka_base_config,
                'group_id': os.getenv('KAFKA_CONSUMER_GROUP_ID', 'anomaly-detector-group'),
                'auto_offset_reset': 'earliest',
                'enable_auto_commit': True,
                'auto_commit_interval_ms': 5000,
                'value_deserializer': safe_json_deserializer
            }
            self.consumer = KafkaConsumer(self.source_topic, **consumer_config)
            logger.debug(f'成功连接到Kafka，消费主题: {self.source_topic}')

            # 初始化Kafka生产者
            producer_config = {
                **kafka_base_config,
                'value_serializer': lambda m: json.dumps(m).encode('utf-8')
            }
            self.producer = KafkaProducer(**producer_config)
            logger.debug(f'成功连接到Kafka，生产主题: {self.agent_topic}')

            # 初始化Redis客户端
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True
            )
            # 测试Redis连接
            self.redis_client.ping()
            logger.debug(f'成功连接到Redis: {self.redis_host}:{self.redis_port}')
            
            # 加载基线前清空Redis数据库
            self.redis_client.flushdb()
            logger.debug("已清空Redis数据库，准备加载持久化基线")
            
            # 尝试加载已保存的基线
            if self.continuous_baseline_enabled:
                logger.debug('持续构建基线模式已开启，将先清空Redis然后加载已有基线继续构建')
                if self.load_baseline_from_file():
                    logger.debug('已成功加载已有基线到Redis，将在此基础上继续收集新基线数据')
                else:
                    logger.debug('未找到已有基线，Redis为空，将从头开始构建基线')
                self.is_baseline_phase = True
                self.baseline_start_time = time.time()
            elif self.load_baseline_from_file():
                self.is_baseline_phase = False
                logger.debug('已加载持久化基线，直接进入异常检测阶段')
            else:
                logger.debug('未找到持久化基线，将启动基线构建阶段')

            if self.record_anomal_enabled:
                logger.debug(f'检测阶段的异常事件记录已开启，将会把异常事件记录到容器内部文件: {self.anomaly_file_path}')
            
            return True
        except KafkaError as e:
            logger.error(f'Kafka客户端初始化失败: {str(e)}')
            return False
        except RedisError as e:
            logger.error(f'Redis客户端初始化失败: {str(e)}')
            return False
        except Exception as e:
            logger.error(f'客户端初始化失败: {str(e)}')
            return False

    def get_rasp_key_fields(self, attack_type):
        """根据attack_type获取对应的rasp关键字段配置"""
        return self.rasp_key_fields_config.get(attack_type, self.rasp_key_fields_config['default'])
    
    def extract_key_fields(self, event):

        """从事件中提取关键字段用于生成哈希键"""
        extracted = {}
        key_fields = {}
        #rasp事件
        if 'event_type' in event:
             #告警类型的事件不产生key fields
            if event['event_type']  != "record_log":
                # 区分Suricata事件和其他告警事件（Suricata事件应在process_event中已处理）
                if event.get('type') == 'suricata':
                    logger.debug(f'Suricata事件在extract_key_fields中被识别，应在process_event中已透传')
                else:
                    logger.debug(f'非record_log事件（非Suricata），不提取key fields: {event.get("event_type")}')
                return None
            # 根据attack_type动态获取关键字段配置
            attack_type = event.get('attack_type', 'default')
            key_fields = self.get_rasp_key_fields(attack_type)
            
            # 如果attack_type是readFile，直接忽略，不提取任何字段
            if key_fields is None:
                logger.debug(f'attack_type为{attack_type}，直接忽略，不提取任何字段')
                return None
        #falco事件
        elif 'output_fields' in event:
            tags = event.get('tags', [])
             #告警类型的事件不产生key fields
            if not isinstance(tags, list) or "behavior-collection" not in tags:
                return None
            key_fields = self.falco_key_fields
        #原始行为事件生成key fileds
        for field in key_fields:
            if isinstance(field, dict):
                # 处理嵌套字段（如 {'attack_params': ['realpath']}）
                for parent_key, child_fields in field.items():
                    if parent_key in event and isinstance(event[parent_key], dict):
                        nested_data = {}
                        for child in child_fields:
                            if child in event[parent_key]:
                                nested_data[child] = event[parent_key][child]
                        if nested_data:
                            extracted[parent_key] = nested_data
            else:
                # 处理顶级字段
                if field in event:
                    extracted[field] = event[field]
        # 从attack_params中删除stack字段
        if 'attack_params' in extracted and isinstance(extracted['attack_params'], dict):
            if 'stack' in extracted['attack_params']:
                del extracted['attack_params']['stack']
                      
        # 可以根据不同的attack_type进行其他特殊处理
        
        return extracted

    def generate_event_hash(self, key_fields_data):
        """基于关键字段生成事件哈希"""
        try:
            # 将数据排序并转换为JSON字符串
            sorted_json = json.dumps(key_fields_data, sort_keys=True, ensure_ascii=False)
            # 计算SHA256哈希
            event_hash = hashlib.sha256(sorted_json.encode('utf-8')).hexdigest()
            # 添加调试输出显示哈希生成过程
            logger.debug(f'生成事件哈希 - 输入数据: {sorted_json}, 生成哈希: {event_hash}')
            return event_hash
        except Exception as e:
            logger.error(f'生成事件哈希失败: {str(e)}')
            return None

    def start_save_timer(self):
        """启动定时保存定时器"""
        if not self.continuous_baseline_enabled:
            return
        
        def save_timer_callback():
            try:
                if self.baseline_modified:
                    logger.debug('定时器触发基线保存检查')
                    # 检查redis客户端是否可用
                    if self.redis_client is None:
                        logger.error('定时器: Redis客户端不可用，跳过保存')
                        return
                    if self.save_baseline_to_file():
                        self.last_baseline_save_time = time.time()
                        self.baseline_modified = False
                        logger.debug(f'定时器: 基线已自动保存到 {self.baseline_file_path}')
                    else:
                        logger.error('定时器: 基线自动保存失败')
            except Exception as e:
                logger.error(f'定时器保存异常: {str(e)}')
            finally:
                # 重新启动定时器
                if self.running:
                    self.save_timer = threading.Timer(self.baseline_save_interval, save_timer_callback)
                    self.save_timer.start()
        
        # 启动定时器
        self.save_timer = threading.Timer(self.baseline_save_interval, save_timer_callback)
        self.save_timer.start()
        logger.debug(f'启动基线定时保存，间隔: {self.baseline_save_interval}秒')
    
    def stop_save_timer(self):
        """停止定时保存定时器"""
        if self.save_timer:
            self.save_timer.cancel()
            self.save_timer = None
            logger.debug('停止基线定时保存')
    
    def is_baseline_complete(self):
        """检查基线构建阶段是否完成"""
        if self.is_baseline_phase and (time.time() - self.baseline_start_time) > self.baseline_duration:
            self.is_baseline_phase = False
            logger.info(f'基线构建阶段完成，共持续 {self.baseline_duration} 秒')
            logger.info(f'正常行为基线数量: {self.redis_client.dbsize()}')
            
            # 保存基线到文件
            if self.save_baseline_to_file():
                logger.debug(f'基线已成功保存到 {self.baseline_file_path}')
            else:
                logger.error('基线保存失败')
        return not self.is_baseline_phase

    def is_suricata_event(self, event):
        """检查是否为 Suricata 事件"""
        # Suricata 事件特征：type 字段为 "suricata"
        return event.get('type') == 'suricata'

    def is_agent_session_event(self, event):
        """检查是否为智能体会话事件"""
        return event.get('type') == 'agent_session'

    def normalize_agent_session_event(self, event):
        """规范化智能体会话事件，用于后续增量裁决"""
        required_fields = ['run_id', 'original_request', 'workspace', 'diff_ref', 'nono']
        missing_fields = [field for field in required_fields if not event.get(field)]
        if missing_fields:
            logger.error(f'智能体会话事件缺少必填字段: {missing_fields}')
            return None

        nono_info = event.get('nono', {})
        if not isinstance(nono_info, dict) or not nono_info.get('session_id'):
            logger.error('智能体会话事件缺少 nono.session_id')
            return None

        diff_ref = event.get('diff_ref', {})
        if not isinstance(diff_ref, dict) or not diff_ref.get('uri') or not diff_ref.get('sha256'):
            logger.error('智能体会话事件缺少 diff_ref.uri 或 diff_ref.sha256')
            return None

        normalized = dict(event)
        normalized.update({
            'source': event.get('source', 'nono-wrapper'),
            'category': 'agent_runtime_change',
            'baseline_action': 'pass_through',
            'event_type': event.get('event_type', 'finished'),
            'received_time': event.get('received_time', datetime.now().isoformat()),
        })
        return normalized

    def process_agent_session_event(self, event):
        """处理智能体会话事件：不进入Redis基线，直接输出到专用Topic"""
        normalized = self.normalize_agent_session_event(event)
        if normalized is None:
            return
        self.producer.send(self.agent_session_topic, value=normalized)
        self.producer.flush()
        logger.debug(f'智能体会话事件已发送到 {self.agent_session_topic}: {normalized.get("run_id")}')

    def should_omit_event(self, event):
        """检查事件是否为openrasp文件读取事件"""
        # 根据attack_type动态获取关键字段配置
        attack_type = event.get('attack_type', 'default')
        key_fields = self.get_rasp_key_fields(attack_type)
        
        # 如果attack_type是readFile，直接忽略，不提取任何字段
        if attack_type == 'readFile':
            logger.debug(f'attack_type为{attack_type}，直接忽略，不提取任何字段{event.get("attack_params",{}).get("realpath","")}')
            return True
        
        # # 针对writeFile事件，检查是否为tmp文件
        # if attack_type == 'writeFile':
        #     attack_params = event.get('attack_params', {})
        #     if isinstance(attack_params, dict):
        #         # 检查realpath是否包含.tmp后缀
        #         realpath = attack_params.get('realpath', '')
                
        #         if realpath.endswith('.tmp'):
        #             logger.debug(f'writeFile事件写入tmp文件，忽略处理 - realpath: {realpath}')
        #             return True
        
        # 针对falco的openat事件，检查是否为tmp文件
        if 'output_fields' in event:
            output_fields = event.get('output_fields', {})
            if isinstance(output_fields, dict):
                evt_type = output_fields.get('evt.type', '')
                fd_name = output_fields.get('fd.name', '')
                
                # 检查是否为openat系统调用且打开的是tmp文件
                if evt_type == 'openat' and fd_name.endswith('.tmp'):
                    logger.debug(f'falco openat事件打开tmp文件，忽略处理 - fd.name: {fd_name}')
                    return True
        
        return False

    def fuzzy_thread_name(self, data):
        """模糊匹配proc.name和proc.cmdline字段，例如：
        输入：
        proc.name = "Thread-5"
        proc.cmdline = "Thread-5 -Djava.util.logging.config.file=/srv/..."
        输出
        proc.name = "Thread-* "
        proc.cmdline = "Thread-* -Djava.util.logging.config.file=/srv/..."
        """
        # 空值检查
        if data is None:
            logger.warning('fuzzy_thread_name接收到None数据，直接返回')
            return None
            
        # 从输入数据中获取proc.name和proc.cmdline字段的值
        # 从输入数据中获取进程名称和命令行参数
        if 'output_fields' not in data or not isinstance(data['output_fields'], dict):
            logger.debug('数据结构中没有output_fields，不进行线程名称模糊匹配')
            return data  # 数据结构异常则直接返回

        output_fields = data['output_fields']
        procname = output_fields.get("proc.name", "")
        proc_cmdline = output_fields.get("proc.cmdline", "")
        logger.debug(f'原始proc.name: {procname}, proc.cmdline: {proc_cmdline}')
        
        # 检查进程名是否以"Thread-"开头
        if procname.startswith("Thread-"):
            output_fields["proc.name"] = "Thread-*"
            logger.debug(f'proc.name线程名称模糊处理: {procname} -> Thread-*')
    
        # 检查命令行参数是否以"Thread-"开头
        if proc_cmdline.startswith("Thread-"):
            idx = proc_cmdline.find(' ')
            if idx != -1:
                proc_cmdline = "Thread-* " + proc_cmdline[idx + 1:]
                output_fields["proc.cmdline"] = proc_cmdline
                data['output_fields'] = output_fields
                logger.debug(f'proc.cmdline线程名称模糊处理: 更新为 {proc_cmdline}')
            else:
                # 如果没有空格，整个命令行就是线程名
                # output_fields["proc.cmdline"] = "Thread-*"
                logger.debug(f'proc.cmdline线程名称模糊处理: 没有空格不更新，保持原来的proc.cmdline: {proc_cmdline}')
        else:
            logger.debug('proc.cmdline不以"Thread-"开头，不进行线程名称模糊匹配')
        
        # 确保返回更新后的数据
        return data
    
    def process_event(self, event):
        """处理单个事件: 基线阶段添加到Redis，检测阶段判断异常"""
        if self.is_agent_session_event(event):
            self.process_agent_session_event(event)
            return

        # Suricata 事件直接透传
        if self.is_suricata_event(event):
            phase = "基线构建阶段" if self.is_baseline_phase else "异常检测阶段"
            logger.debug(f'[{phase}] 检测到 Suricata 事件，直接透传到 agent')
            self.producer.send(self.agent_topic, value=event)
            self.producer.flush()
            logger.debug(f'Suricata 事件已透传到 agent: {event}')
            return

        if self.should_omit_event(event):
            # 安全地获取文件路径信息
            attack_params = event.get("attack_params", {})
            if isinstance(attack_params, dict):
                path_info = attack_params.get("realpath", "") or attack_params.get("path", "")
            else:
                path_info = str(attack_params) if attack_params else ""
            return

        # 提取关键字段并生成哈希
        key_fields_data = self.extract_key_fields(event)

        # 模糊匹配线程名称，不区分阶段
        if self.enable_thread_name_fuzzy_match:
            logger.debug(f'线程名称模糊匹配{key_fields_data}')
            key_fields_data = self.fuzzy_thread_name(key_fields_data)
        else:
            logger.debug('线程名称模糊匹配功能未开启')

        # 模糊匹配文件路径中的数字，不区分阶段
        if self.enable_filepath_num_fuzzy_match and key_fields_data is not None:
            if 'output_fields' in key_fields_data and isinstance(key_fields_data['output_fields'], dict) and 'fd.name' in key_fields_data['output_fields']:
                original_path = key_fields_data['output_fields']['fd.name']
                fuzzy_path = ''.join(['*' if char.isdigit() else char for char in original_path])
                key_fields_data['output_fields']['fd.name'] = fuzzy_path
                logger.debug(f'文件路径数字模糊匹配 - 原始路径: {original_path}, 模糊路径: {fuzzy_path}')    

        #key_fields_data为None表示采集到了告警事件，告警事件应立即发送到agent
        if  key_fields_data is None:
            phase = "基线构建阶段" if self.is_baseline_phase else "异常检测阶段"
            logger.warning(f'[{phase}] 检测到异常告警，发送到agent')
            # 发送到agent主题
            self.producer.send(self.agent_topic, value=event)
            self.producer.flush()
            logger.debug(f'异常事件已发送到agent: {event}')
            return
        event_hash = self.generate_event_hash(key_fields_data)
        if not event_hash:
            logger.error('生成事件哈希失败，跳过当前事件')
            return
        
        # 检查事件是否已存在于Redis中
        event_exists = self.redis_client.exists(event_hash)
        
        # 只在事件不存在时打印接收到的事件信息
        if not event_exists:
            event_type = 'RASP' if 'event_type' in event else 'Falco' if 'output_fields' in event else 'Unknown'
            logger.debug(f'接收到新事件 [{event_type}]: {event.get("event_type", event.get("rule", "unknown"))}')
            logger.debug(f'接收到事件: {json.dumps(event, ensure_ascii=False, indent=2)}')
        
        if self.is_baseline_phase:
            # 基线构建阶段 - 添加到Redis
            try:
                # 根据环境变量决定存储value类型
                value_type = self.redis_value_type
                if value_type == 'key_fields':
                    # 存储关键字段内容 (复用已提取的key_fields_data)
                    value = json.dumps(key_fields_data)
                else:
                    # 默认存储时间戳
                    value = event.get('event_time', datetime.now().isoformat())
                     
                # 只在事件不存在时添加到Redis并打印详细信息
                if not event_exists:
                    self.redis_client.set(event_hash, value)
                    self.baseline_modified = True  # 标记基线有更新
                    # 只在事件不存在时打印详细调试信息
                    logger.debug(f'基线事件详情 - 哈希: {event_hash}, 关键字段: {json.dumps(key_fields_data, ensure_ascii=False, indent=2)}, 存储值: {value}')
                    logger.debug(f'基线事件添加成功，哈希: {event_hash}')
                else:
                    # 事件已存在，只记录极简单的日志
                    logger.debug(f'基线事件已存在，跳过: {event_hash[:8]}...')
            except RedisError as e:
                logger.error(f'Redis存储失败: {str(e)}')
        else:
            # 异常检测阶段 - 检查是否存在于基线中
            try:
                if not event_exists:
                    # 只在事件不存在时打印详细信息并发送到agent
                    event_type = 'RASP' if 'event_type' in event else 'Falco' if 'output_fields' in event else 'Unknown'
                    logger.warning(f'检测到异常原始行为事件 [{event_type}], 发送到agent')
                    logger.debug(f'异常事件详情 - 哈希: {event_hash}, 关键字段: {json.dumps(key_fields_data, ensure_ascii=False, indent=2)}')
                    # 发送到agent主题
                    self.producer.send(self.agent_topic, value=event)
                    self.producer.flush()
                    logger.debug(f'异常事件已发送到 {self.agent_topic} 主题')

                    # 保存异常数据到内存，使用与基线相同的hash逻辑，避免重复保存
                    anomaly_saved = self.save_anomaly_to_memory(event_hash, event, key_fields_data)
                    if anomaly_saved:
                        logger.debug(f'新异常数据已记录 - 哈希: {event_hash}')
                    else:
                        logger.debug(f'重复异常数据已跳过 - 哈希: {event_hash}')
                else:
                    # 事件正常，只打印极简日志
                    logger.debug(f'事件正常: {event_hash[:8]}...')
            except RedisError as e:
                logger.error(f'Redis查询失败: {str(e)}')
            except KafkaError as e:
                logger.error(f'Kafka发送失败: {str(e)}')
    
    def save_baseline_to_file(self):
        """将Redis中的基线数据保存到文件"""
        try:
            baseline_data = {}
            cursor = '0'
            
            # 使用scan遍历所有键，避免阻塞Redis
            while cursor != 0:
                cursor, keys = self.redis_client.scan(cursor=cursor, count=1000)
                if keys:
                    values = self.redis_client.mget(keys)
                    for key, value in zip(keys, values):
                        baseline_data[key] = value
            
            # 保存到JSON文件
            with open(self.baseline_file_path, 'w', encoding='utf-8') as f:
                json.dump(baseline_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f'保存基线到文件失败: {str(e)}')
            return False

    def load_baseline_from_file(self):
        """从文件加载基线数据到Redis"""
        try:
            if not os.path.exists(self.baseline_file_path):
                return False
            
            with open(self.baseline_file_path, 'r', encoding='utf-8') as f:
                baseline_data = json.load(f)
            
            if not baseline_data:
                logger.warning('基线文件为空，将重新构建基线')
                return False
            
            # 批量插入数据到Redis
            pipeline = self.redis_client.pipeline()
            for key, value in baseline_data.items():
                pipeline.set(key, value)
            pipeline.execute()
            
            logger.debug(f'从 {self.baseline_file_path} 加载基线成功，共加载 {len(baseline_data)} 条记录')
            return True
        except Exception as e:
            logger.error(f'从文件加载基线失败: {str(e)}')
            return False
        
    def start_record_anomalies_timer(self):
        """启动定时保存定时器"""
        if not self.record_anomal_enabled:
            return
        
        def record_anomalies_timer_callback():
            try:                
                # 检查并保存异常数据
                if self.anomalies_modified:
                    logger.debug('定时器触发异常数据保存检查')
                    if self.save_anomalies_to_file():
                        self.last_anomal_save_time = time.time()
                        self.anomalies_modified = False
                        logger.debug(f'定时器: 异常数据已自动保存到 {self.anomaly_file_path}')
                    else:
                        logger.error('定时器: 异常数据自动保存失败')
                        
            except Exception as e:
                logger.error(f'定时器保存异常: {str(e)}')
            finally:
                # 重新启动定时器
                if self.running:
                    self.anomal_save_timer = threading.Timer(self.anomal_save_interval, record_anomalies_timer_callback)
                    self.anomal_save_timer.start()
        # 启动定时器
        self.anomal_save_timer = threading.Timer(self.anomal_save_interval, record_anomalies_timer_callback)
        self.anomal_save_timer.start()
        logger.debug(f'启动异常事件定时保存，间隔: {self.anomal_save_interval}秒')
    
    def stop_anomal_timer(self):
        """停止定时保存定时器"""
        if self.anomal_save_timer:
            self.anomal_save_timer.cancel()
            self.anomal_save_timer = None
            logger.debug('停止异常事件（非收集状态）定时保存')
        
    def save_anomaly_to_memory(self, event_hash, event, key_fields_data):
        """将异常数据保存到内存中，格式与基线数据保持一致，避免重复保存"""
        try:
            # 检查该异常是否已经存在，如果已存在则不重复标记为需要保存
            if event_hash in self.anomalies:
                logger.debug(f'异常数据已存在，跳过保存 - 哈希: {event_hash}')
                return False
            
            # 根据环境变量决定存储value类型，与基线逻辑保持一致
            value_type = self.redis_value_type
            if value_type == 'key_fields':
                # 存储关键字段内容，与基线存储逻辑一致
                value = json.dumps(key_fields_data)
            else:
                # 默认存储时间戳，与基线存储逻辑一致
                value = event.get('event_time', datetime.now().isoformat())
            
            # 使用事件哈希作为key，与基线格式保持一致 {hash: value}
            self.anomalies[event_hash] = value
            self.anomalies_modified = True  # 标记异常数据有更新
            
            logger.debug(f'异常数据已保存到内存 - 哈希: {event_hash}, 值: {value}')
            return True
        except Exception as e:
            logger.error(f'保存异常数据到内存失败: {str(e)}')
            return False
    
    def save_anomalies_to_file(self):
        """将内存中的异常数据保存到文件"""
        try:
            # 保存到JSON文件
            with open(self.anomaly_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.anomalies, f, ensure_ascii=False, indent=2)
            
            logger.debug(f'异常数据已保存到文件 {self.anomaly_file_path}，共 {len(self.anomalies)} 条记录')
            return True
        except Exception as e:
            logger.error(f'保存异常数据到文件失败: {str(e)}')
            return False


    def run(self):
        """主运行函数"""
        logger.info('异常事件检测程序启动')
        logger.info(f'基线构建时长: {self.baseline_duration}秒')

        # 初始化客户端
        if not self.initialize_clients():
            logger.error('客户端初始化失败，程序退出')
            return
        
        try:
            # 启动定时保存（如果开启持续构建模式）
            if self.continuous_baseline_enabled:
                self.running = True
                self.start_save_timer()
            elif self.record_anomal_enabled:
                self.running = True
                self.start_record_anomalies_timer()
            
            # 主循环消费事件
            for message in self.consumer:
                try:
                    event = message.value
                    if event is None:
                        logger.warning('收到空消息或非JSON格式消息，已跳过')
                        continue
                    # 检查基线阶段是否完成
                    self.is_baseline_complete()

                    # 处理事件
                    self.process_event(event)

                    # 事件处理中的保存逻辑移除，改为定时器处理
                    # if self.continuous_baseline_enabled:
                    #     self.save_baseline_if_needed()

                except json.JSONDecodeError:
                    logger.warning('事件JSON解析失败，已跳过该消息')
                except Exception as e:
                    logger.error(f'事件处理异常: {str(e)}')

        except KeyboardInterrupt:
            logger.debug('程序被用户中断')
        except Exception as e:
            logger.error(f'程序运行异常: {str(e)}')
        finally:
            # 停止定时器
            self.running = False
            self.stop_save_timer()
            self.stop_anomal_timer()
            # 清理资源
            if self.consumer:
                self.consumer.close()
            if self.producer:
                self.producer.close()
            logger.debug('异常事件检测程序退出')

if __name__ == '__main__':
    detector = AnomalyDetector()
    detector.run()
