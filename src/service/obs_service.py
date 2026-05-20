"""
对象存储上传服务
用于将本地文件上传到公司 OSS 接口并获取可访问的 URL。
"""
import glob
import hashlib
import logging
import mimetypes
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List, Set
from urllib.parse import urlparse

import aiohttp

try:
    from obs import ObsClient, PutObjectHeader, GetObjectHeader
    from obs.model import CompletePart
except ImportError:
    ObsClient = None
    PutObjectHeader = None
    GetObjectHeader = None
    CompletePart = None

logger = logging.getLogger(__name__)


class ProgressCallback:
    """上传/下载进度回调类"""

    def __init__(self, total_size: int, callback: Optional[Callable[[int, int, float], None]] = None):
        self.total_size = total_size
        self.transferred = 0
        self.callback = callback
        self.start_time = datetime.now()

    def __call__(self, transferred_amount: int):
        """进度回调函数"""
        self.transferred += transferred_amount
        progress = (self.transferred / self.total_size) * 100 if self.total_size > 0 else 0

        if self.callback:
            self.callback(self.transferred, self.total_size, progress)

        # 记录进度日志
        if self.transferred % (1024 * 1024) == 0 or progress >= 100:  # 每1MB或完成时记录
            elapsed = (datetime.now() - self.start_time).total_seconds()
            speed = self.transferred / elapsed if elapsed > 0 else 0
            logger.info(f"传输进度: {progress:.1f}% ({self.transferred}/{self.total_size} bytes), "
                        f"速度: {speed / 1024 / 1024:.2f} MB/s")


class OBSService:
    """对象存储上传服务类，保留类名以兼容现有调用。"""

    def __init__(self,
                 access_key_id: Optional[str] = None,
                 secret_access_key: Optional[str] = None,
                 server: Optional[str] = None,
                 bucket_name: Optional[str] = None):
        """
        初始化OBS服务
        
        Args:
            access_key_id: 访问密钥ID
            secret_access_key: 秘密访问密钥
            server: OBS服务端点
            bucket_name: 存储桶名称
        """
        # 从环境变量或参数获取配置
        self.access_key_id = access_key_id or os.getenv('OBS_ACCESS_KEY_ID', 'HPUADWBFTH4FRCDUPZT7')
        self.secret_access_key = secret_access_key or os.getenv('OBS_SECRET_ACCESS_KEY',
                                                                'ijSlMMnc2kkiV3lrHAKORpHbSL41xyb9ziZOYaTC')
        self.server = server or os.getenv('OBS_SERVER', 'obs.cn-north-4.myhuaweicloud.com')
        self.bucket_name = bucket_name or os.getenv('OBS_BUCKET_NAME', 'hackathon')

        if not all([self.access_key_id, self.secret_access_key, self.bucket_name]):
            logger.warning("OBS配置不完整，请设置环境变量或传入参数")

        # 初始化OBS客户端
        self.obs_client = None

        # 线程池用于异步操作
        self.executor = ThreadPoolExecutor(max_workers=5)

        # 旧 OBS 私有方法可能仍被外部误用，保留这些配置避免属性缺失。
        self.multipart_threshold = 100 * 1024 * 1024
        self.part_size = 10 * 1024 * 1024

        self.upload_url = os.getenv(
            "OSS_UPLOAD_URL",
            os.getenv("FALLBACK_UPLOAD_URL", "http://lab-pf-hermit-purple.beta.qunar.com/oss/upload")
        )
        self.upload_field_name = os.getenv("OSS_UPLOAD_FIELD_NAME", "file")
        self.upload_timeout_seconds = int(os.getenv("OSS_UPLOAD_TIMEOUT_SECONDS", "300"))

    @staticmethod
    def _extract_upload_url(payload: Any) -> Optional[str]:
        """兼容不同上传接口响应结构，提取可访问 URL。"""
        if isinstance(payload, str):
            return payload if payload.startswith(("http://", "https://")) else None

        if not isinstance(payload, dict):
            return None

        for key in ("url", "oss_url", "fileUrl", "file_url", "downloadUrl", "download_url"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value

        data = payload.get("data")
        if isinstance(data, str):
            return OBSService._extract_upload_url(data)
        if isinstance(data, dict):
            return OBSService._extract_upload_url(data)
        if isinstance(data, list):
            for item in data:
                url = OBSService._extract_upload_url(item)
                if url:
                    return url

        result = payload.get("result")
        if isinstance(result, (dict, list)):
            return OBSService._extract_upload_url({"data": result})

        return None

    async def _upload_via_oss(self, file_path: str) -> Optional[str]:
        """使用公司内网 OSS 上传接口，返回可访问 URL。"""
        try:
            timeout = aiohttp.ClientTimeout(total=self.upload_timeout_seconds)
            form = aiohttp.FormData()
            with open(file_path, "rb") as f:
                form.add_field(
                    self.upload_field_name,
                    f,
                    filename=Path(file_path).name,
                    content_type=mimetypes.guess_type(file_path)[0] or "application/octet-stream"
                )
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self.upload_url, data=form) as resp:
                        response_text = await resp.text()
                        if resp.status >= 400:
                            logger.error(f"OSS上传失败: status={resp.status}, body={response_text}")
                            return None

                        try:
                            payload = await resp.json(content_type=None)
                        except Exception:
                            payload = response_text

            url = self._extract_upload_url(payload)
            if url:
                logger.info(f"OSS上传成功: {file_path} -> {url}")
                return url

            logger.error(f"OSS上传响应中未找到URL: {payload}")
            return None
        except Exception as e:
            logger.error(f"OSS上传异常: {e}")
            return None

    def _init_client(self):
        """兼容旧接口：华为云 OBS 已停用，不再初始化客户端。"""
        self.obs_client = None

    def _get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """获取文件元数据"""
        file_stat = os.stat(file_path)
        content_type, _ = mimetypes.guess_type(file_path)

        # 计算文件MD5
        md5_hash = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)

        return {
            'size': file_stat.st_size,
            'content_type': content_type or 'application/octet-stream',
            'md5': md5_hash.hexdigest(),
            'last_modified': datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
            'filename': Path(file_path).name
        }

    def _upload_small_file(self, file_path: str, object_key: str,
                           progress_callback: Optional[ProgressCallback] = None) -> Optional[str]:
        """上传小文件（<100MB）"""
        try:
            metadata = self._get_file_metadata(file_path)

            # 设置上传头信息
            headers = PutObjectHeader()
            headers.contentType = metadata['content_type']
            headers.contentMd5 = metadata['md5']

            # 自定义元数据
            headers.metadata = {
                'original-filename': metadata['filename'],
                'upload-time': datetime.now().isoformat(),
                'file-size': str(metadata['size'])
            }

            # 执行上传
            with open(file_path, 'rb') as f:
                if progress_callback:
                    # 模拟进度回调
                    content = f.read()
                    progress_callback(len(content))
                    resp = self.obs_client.putObject(
                        bucketName=self.bucket_name,
                        objectKey=object_key,
                        content=content,
                        headers=headers
                    )
                else:
                    resp = self.obs_client.putFile(
                        bucketName=self.bucket_name,
                        objectKey=object_key,
                        file_path=file_path,
                        headers=headers
                    )

            if resp.status < 300:
                file_url = f"https://{self.bucket_name}.{self.server}/{object_key}"
                logger.info(f"小文件上传成功: {file_path} -> {file_url}")
                return file_url
            else:
                logger.error(f"文件上传失败: {resp.errorCode} - {resp.errorMessage}")
                return None

        except Exception as e:
            logger.error(f"小文件上传异常: {str(e)}")
            return None

    def _upload_large_file(self, file_path: str, object_key: str,
                           progress_callback: Optional[ProgressCallback] = None) -> Optional[str]:
        """上传大文件（>=100MB）使用分片上传"""
        try:
            metadata = self._get_file_metadata(file_path)
            file_size = metadata['size']

            # 初始化分片上传
            resp = self.obs_client.initiateMultipartUpload(
                bucketName=self.bucket_name,
                objectKey=object_key,
                contentType=metadata['content_type'],
                metadata={
                    'original-filename': metadata['filename'],
                    'upload-time': datetime.now().isoformat(),
                    'file-size': str(file_size)
                }
            )

            if resp.status >= 300:
                logger.error(f"初始化分片上传失败: {resp.errorCode} - {resp.errorMessage}")
                return None

            upload_id = resp.body.uploadId
            parts = []
            part_number = 1

            try:
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(self.part_size)
                        if not chunk:
                            break

                        # 上传分片
                        part_resp = self.obs_client.uploadPart(
                            bucketName=self.bucket_name,
                            objectKey=object_key,
                            partNumber=part_number,
                            uploadId=upload_id,
                            content=chunk
                        )

                        if part_resp.status >= 300:
                            raise Exception(f"分片{part_number}上传失败: {part_resp.errorCode}")

                        parts.append(CompletePart(
                            partNumber=part_number,
                            etag=part_resp.body.etag
                        ))

                        # 更新进度
                        if progress_callback:
                            progress_callback(len(chunk))

                        part_number += 1

                # 完成分片上传
                complete_resp = self.obs_client.completeMultipartUpload(
                    bucketName=self.bucket_name,
                    objectKey=object_key,
                    uploadId=upload_id,
                    parts=parts
                )

                if complete_resp.status < 300:
                    file_url = f"https://{self.bucket_name}.{self.server}/{object_key}"
                    logger.info(f"大文件分片上传成功: {file_path} -> {file_url}")
                    return file_url
                else:
                    logger.error(f"完成分片上传失败: {complete_resp.errorCode}")
                    return None

            except Exception as e:
                # 取消分片上传
                self.obs_client.abortMultipartUpload(
                    bucketName=self.bucket_name,
                    objectKey=object_key,
                    uploadId=upload_id
                )
                raise e

        except Exception as e:
            logger.error(f"大文件上传异常: {str(e)}")
            return None

    async def upload_file(self, file_path: str, filename: Optional[str] = None,
                          progress_callback: Optional[Callable[[int, int, float], None]] = None) -> Optional[str]:
        """
        上传文件并返回可访问的URL

        Args:
            file_path: 本地文件路径
            filename: 目标文件名（可选）
            progress_callback: 进度回调函数 (transferred, total, progress_percent)

        Returns:
            str: 文件的可访问URL，失败返回None
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"文件不存在: {file_path}")
                return None

            # 生成对象键
            if not filename:
                filename = Path(file_path).name

            # 创建进度回调
            file_size = os.path.getsize(file_path)
            progress_cb = ProgressCallback(file_size, progress_callback) if progress_callback else None
            if progress_cb:
                progress_cb(file_size)

            return await self._upload_via_oss(file_path)

        except Exception as e:
            logger.error(f"文件上传失败: {str(e)}")
            return None

    async def upload_file_for_path(self, file_path: str, oss_path: str, filename: Optional[str] = None,
                                   progress_callback: Optional[Callable[[int, int, float], None]] = None) -> Optional[
        str]:
        """
        上传文件并返回可访问的URL

        Args:
            file_path: 本地文件路径
            filename: 目标文件名（可选）
            progress_callback: 进度回调函数 (transferred, total, progress_percent)

        Returns:
            str: 文件的可访问URL，失败返回None
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"文件不存在: {file_path}")
                return None

            # 创建进度回调
            file_size = os.path.getsize(file_path)
            progress_cb = ProgressCallback(file_size, progress_callback) if progress_callback else None
            if progress_cb:
                progress_cb(file_size)

            if oss_path:
                logger.debug(f"OSS上传接口不支持指定对象路径，忽略 oss_path={oss_path}")

            return await self._upload_via_oss(file_path)

        except Exception as e:
            logger.error(f"文件上传失败: {str(e)}")
            return None

    async def upload_from_url(
            self,
            url: str,
            filename: Optional[str] = None,
            oss_path: Optional[str] = None,
            headers: Optional[Dict[str, str]] = None,
            timeout_seconds: int = 60,
            progress_callback: Optional[Callable[[int, int, float], None]] = None
    ) -> Optional[str]:
        """
        从远程URL下载文件到临时目录并上传到OBS，返回新的OSS可访问URL。

        Args:
            url: 远程文件URL（支持内网/公网）
            filename: 指定上传文件名（可选），默认从URL解析
            oss_path: 指定OBS对象键（可选），若提供则使用精确路径上传
            headers: 下载时使用的HTTP头（可选）
            timeout_seconds: 下载超时时间
            progress_callback: 上传进度回调（可选）

        Returns:
            str: OSS访问URL；如果下载或上传失败返回None
        """
        if not url:
            logger.error("upload_from_url: URL 为空")
            return None

        # 解析扩展名与默认文件名
        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1] or ".jpg"
        use_filename = filename or (Path(parsed.path).name or f"file{ext}")

        temp_path = None
        try:
            # 下载到临时文件
            fd, temp_path = tempfile.mkstemp(suffix=ext, prefix="url_dl_")
            os.close(fd)

            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=timeout) as resp:
                    resp.raise_for_status()
                    with open(temp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 64):
                            f.write(chunk)

            # 上传到OBS
            if oss_path:
                # 使用精确对象键
                result_url = await self.upload_file_for_path(
                    file_path=temp_path,
                    oss_path=oss_path,
                    filename=use_filename,
                    progress_callback=progress_callback
                )
            else:
                # 使用默认 uploads/<timestamp>_<filename>
                result_url = await self.upload_file(
                    file_path=temp_path,
                    filename=use_filename,
                    progress_callback=progress_callback
                )

            return result_url

        except Exception as e:
            logger.error(f"upload_from_url: 下载或上传失败: {e}")
            return None
        finally:
            try:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

    async def download_file(self, object_key: str, local_path: str,
                            progress_callback: Optional[Callable[[int, int, float], None]] = None) -> bool:
        """
        从OBS下载文件到本地
        
        Args:
            object_key: OBS对象键
            local_path: 本地保存路径
            progress_callback: 进度回调函数
            
        Returns:
            bool: 下载成功返回True
        """
        if not self.obs_client:
            logger.error("OBS客户端未初始化")
            return False

        try:
            # 获取对象元数据
            head_resp = self.obs_client.getObjectMetadata(
                bucketName=self.bucket_name,
                objectKey=object_key
            )

            if head_resp.status >= 300:
                logger.error(f"获取对象元数据失败: {head_resp.errorCode}")
                return False

            file_size = int(head_resp.body.contentLength)

            # 创建进度回调
            progress_cb = ProgressCallback(file_size, progress_callback) if progress_callback else None

            # 确保目录存在
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # 下载文件
            def _download():
                with open(local_path, 'wb') as f:
                    resp = self.obs_client.getObject(
                        bucketName=self.bucket_name,
                        objectKey=object_key
                    )

                    if resp.status >= 300:
                        raise Exception(f"下载失败: {resp.errorCode}")

                    # 分块读取并写入
                    while True:
                        chunk = resp.body.response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        if progress_cb:
                            progress_cb(len(chunk))

                return True

            # 在线程池中执行下载
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(self.executor, _download)

            if result:
                logger.info(f"文件下载成功: {object_key} -> {local_path}")

            return result

        except Exception as e:
            logger.error(f"文件下载失败: {str(e)}")
            return False

    def delete_file(self, filename: str) -> bool:
        """
        删除OBS中的文件
        
        Args:
            filename: 文件名或对象键
            
        Returns:
            bool: 删除成功返回True
        """
        if not self.obs_client:
            logger.error("OBS客户端未初始化")
            return False

        try:
            # 如果是完整的对象键，直接使用；否则在uploads目录下查找
            if filename.startswith('uploads/'):
                object_key = filename
            else:
                # 列出所有匹配的对象
                resp = self.obs_client.listObjects(
                    bucketName=self.bucket_name,
                    prefix=f"uploads/",
                    max_keys=1000
                )

                if resp.status >= 300:
                    logger.error(f"列出对象失败: {resp.errorCode}")
                    return False

                # 查找匹配的文件
                object_key = None
                for obj in resp.body.contents:
                    if obj.key.endswith(filename):
                        object_key = obj.key
                        break

                if not object_key:
                    logger.warning(f"未找到文件: {filename}")
                    return True  # 文件不存在也算删除成功

            # 删除对象
            resp = self.obs_client.deleteObject(
                bucketName=self.bucket_name,
                objectKey=object_key
            )

            if resp.status < 300:
                logger.info(f"文件删除成功: {object_key}")
                return True
            else:
                logger.error(f"文件删除失败: {resp.errorCode}")
                return False

        except Exception as e:
            logger.error(f"文件删除异常: {str(e)}")
            return False

    def get_file_metadata(self, object_key: str) -> Optional[Dict[str, Any]]:
        """
        获取文件元数据
        
        Args:
            object_key: 对象键
            
        Returns:
            Dict: 文件元数据，失败返回None
        """
        if not self.obs_client:
            logger.error("OBS客户端未初始化")
            return None

        try:
            resp = self.obs_client.getObjectMetadata(
                bucketName=self.bucket_name,
                objectKey=object_key
            )

            if resp.status >= 300:
                logger.error(f"获取元数据失败: {resp.errorCode}")
                return None

            metadata = {
                'size': int(resp.body.contentLength),
                'content_type': resp.body.contentType,
                'etag': resp.body.etag,
                'last_modified': resp.body.lastModified,
                'object_key': object_key
            }

            # 添加自定义元数据
            if hasattr(resp.body, 'metadata') and resp.body.metadata:
                metadata.update(resp.body.metadata)

            return metadata

        except Exception as e:
            logger.error(f"获取元数据异常: {str(e)}")
            return None

    def list_files(self, prefix: str = "uploads/", max_keys: int = 1000) -> Optional[list]:
        """
        列出存储桶中的文件
        
        Args:
            prefix: 对象键前缀
            max_keys: 最大返回数量
            
        Returns:
            list: 文件列表，失败返回None
        """
        if not self.obs_client:
            logger.error("OBS客户端未初始化")
            return None

        try:
            resp = self.obs_client.listObjects(
                bucketName=self.bucket_name,
                prefix=prefix,
                max_keys=max_keys
            )

            if resp.status >= 300:
                logger.error(f"列出对象失败: {resp.errorCode}")
                return None

            files = []
            for obj in resp.body.contents:
                files.append({
                    'key': obj.key,
                    'size': obj.size,
                    'last_modified': obj.lastModified,
                    'etag': obj.etag,
                    'url': f"https://{self.bucket_name}.{self.server}/{obj.key}"
                })

            return files

        except Exception as e:
            logger.error(f"列出文件异常: {str(e)}")
            return None

    def __del__(self):
        """析构函数，关闭OBS客户端"""
        if self.obs_client:
            try:
                self.obs_client.close()
            except:
                pass

        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    def upload_files_from_dir(self, output_dir: str, file_patterns: List[str] = None) -> List[str]:
        """
        扫描一个目录中【匹配多种格式】的文件，并并发上传它们。

        Args:
            output_dir: 包含文件的目录 (例如: .../video/1)
            file_patterns: 要匹配的文件格式【列表】
                           (例如: ["*.jpg", "*.png", "*.jpeg"])
                           如果为 None，则默认为 ["*.jpg"]

        Returns:
            一个包含所有成功上传的URL的列表
        """

        # 1. 设置默认值并准备一个集合 (set) 来存储唯一路径
        if file_patterns is None:
            file_patterns = ["*.jpg"]

        all_file_paths: Set[str] = set()

        # 2. 遍历所有传入的格式，查找文件
        for pattern in file_patterns:
            search_pattern = os.path.join(output_dir, pattern)
            # 找到所有匹配当前格式的文件
            found_files = glob.glob(search_pattern)
            # 将它们全部添加到集合中，set 会自动处理重复
            all_file_paths.update(found_files)

        # 3. 检查是否找到了文件
        if not all_file_paths:
            logger.warning(f"在 {output_dir} 中未找到匹配 {file_patterns} 的文件，跳过上传。")
            return []

        logger.info(f"在 {output_dir} 中找到 {len(all_file_paths)} 个唯一匹配文件，准备并发上传...")

        # 4. 为每个文件创建一个上传任务
        upload_tasks = []
        for file_path in all_file_paths:
            task = self.upload_file(
                file_path=file_path,
                progress_callback=None
            )
            upload_tasks.append(task)

        # 5. 使用 asyncio.gather 并发执行所有上传任务
        try:
            results = asyncio.gather(*upload_tasks)

            # 6. 过滤掉上传失败的结果 (返回值为 None)
            successful_urls = [url for url in results if url is not None]

            logger.info(f"成功上传 {len(successful_urls)} / {len(all_file_paths)} 个文件。")
            return successful_urls

        except Exception as e:
            logger.error(f"并发上传文件时发生错误: {e}", exc_info=True)
            return []


# 创建服务实例
obs_service = OBSService()
