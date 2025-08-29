use pyo3::prelude::*;
use anyhow::{Context, Result};
use chrono::prelude::*;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::io::{BufReader, Read};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::Instant;

#[cfg(target_arch = "x86_64")]
use std::arch::x86_64::*;

/// Python绑定的视频帧结构
#[pyclass]
#[derive(Debug, Clone)]
pub struct PyVideoFrame {
    #[pyo3(get)]
    pub frame_number: usize,
    #[pyo3(get)]
    pub width: usize,
    #[pyo3(get)]
    pub height: usize,
    pub data: Vec<u8>,
}

#[pymethods]
impl PyVideoFrame {
    #[new]
    fn new(frame_number: usize, width: usize, height: usize, data: Vec<u8>) -> Self {
        // 确保数据长度是32的倍数以支持AVX2处理
        let mut aligned_data = data;
        let remainder = aligned_data.len() % 32;
        if remainder != 0 {
            aligned_data.resize(aligned_data.len() + (32 - remainder), 0);
        }
        
        Self {
            frame_number,
            width,
            height,
            data: aligned_data,
        }
    }
    
    /// 获取帧数据
    fn get_data(&self) -> &[u8] {
        let pixel_count = self.width * self.height;
        &self.data[..pixel_count]
    }
    
    /// 计算与另一帧的差异
    fn calculate_difference(&self, other: &PyVideoFrame) -> PyResult<f64> {
        if self.width != other.width || self.height != other.height {
            return Ok(f64::MAX);
        }
        
        let total_pixels = self.width * self.height;
        let total_diff: u64 = self.data[..total_pixels]
            .iter()
            .zip(other.data[..total_pixels].iter())
            .map(|(a, b)| (*a as i32 - *b as i32).abs() as u64)
            .sum();
        
        Ok(total_diff as f64 / total_pixels as f64)
    }
    
    /// 使用SIMD优化计算帧差异
    #[pyo3(signature = (other, block_size=None))]
    fn calculate_difference_simd(&self, other: &PyVideoFrame, block_size: Option<usize>) -> PyResult<f64> {
        let block_size = block_size.unwrap_or(8192);
        Ok(self.calculate_difference_parallel_simd(other, block_size, true))
    }
}

impl PyVideoFrame {
    /// 使用并行SIMD处理计算帧差异
    fn calculate_difference_parallel_simd(&self, other: &PyVideoFrame, block_size: usize, use_simd: bool) -> f64 {
        if self.width != other.width || self.height != other.height {
            return f64::MAX;
        }
        
        let total_pixels = self.width * self.height;
        let num_blocks = (total_pixels + block_size - 1) / block_size;
        
        let total_diff: u64 = (0..num_blocks)
            .into_par_iter()
            .map(|block_idx| {
                let start = block_idx * block_size;
                let end = ((block_idx + 1) * block_size).min(total_pixels);
                let block_len = end - start;
                
                if use_simd {
                    #[cfg(target_arch = "x86_64")]
                    {
                        unsafe {
                            if std::arch::is_x86_feature_detected!("avx2") {
                                return self.calculate_difference_avx2_block(&other.data, start, block_len);
                            } else if std::arch::is_x86_feature_detected!("sse2") {
                                return self.calculate_difference_sse2_block(&other.data, start, block_len);
                            }
                        }
                    }
                }
                
                // 标量实现回退
                self.data[start..end]
                    .iter()
                    .zip(other.data[start..end].iter())
                    .map(|(a, b)| (*a as i32 - *b as i32).abs() as u64)
                    .sum()
            })
            .sum();
        
        total_diff as f64 / total_pixels as f64
    }
    
    /// AVX2 优化的块处理
    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    unsafe fn calculate_difference_avx2_block(&self, other_data: &[u8], start: usize, len: usize) -> u64 {
        let mut total_diff = 0u64;
        let chunks = len / 32;
        
        for i in 0..chunks {
            let offset = start + i * 32;
            
            let a = _mm256_loadu_si256(self.data.as_ptr().add(offset) as *const __m256i);
            let b = _mm256_loadu_si256(other_data.as_ptr().add(offset) as *const __m256i);
            
            let diff = _mm256_sad_epu8(a, b);
            let result = _mm256_extract_epi64(diff, 0) as u64 +
                        _mm256_extract_epi64(diff, 1) as u64 +
                        _mm256_extract_epi64(diff, 2) as u64 +
                        _mm256_extract_epi64(diff, 3) as u64;
            
            total_diff += result;
        }
        
        // 处理剩余字节
        for i in (start + chunks * 32)..(start + len) {
            total_diff += (self.data[i] as i32 - other_data[i] as i32).abs() as u64;
        }
        
        total_diff
    }
    
    /// SSE2 优化的块处理
    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "sse2")]
    unsafe fn calculate_difference_sse2_block(&self, other_data: &[u8], start: usize, len: usize) -> u64 {
        let mut total_diff = 0u64;
        let chunks = len / 16;
        
        for i in 0..chunks {
            let offset = start + i * 16;
            
            let a = _mm_loadu_si128(self.data.as_ptr().add(offset) as *const __m128i);
            let b = _mm_loadu_si128(other_data.as_ptr().add(offset) as *const __m128i);
            
            let diff = _mm_sad_epu8(a, b);
            let result = _mm_extract_epi64(diff, 0) as u64 + _mm_extract_epi64(diff, 1) as u64;
            
            total_diff += result;
        }
        
        // 处理剩余字节
        for i in (start + chunks * 16)..(start + len) {
            total_diff += (self.data[i] as i32 - other_data[i] as i32).abs() as u64;
        }
        
        total_diff
    }
}

/// 性能测试结果
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PyPerformanceResult {
    #[pyo3(get)]
    pub test_name: String,
    #[pyo3(get)]
    pub video_file: String,
    #[pyo3(get)]
    pub total_time_ms: f64,
    #[pyo3(get)]
    pub frame_extraction_time_ms: f64,
    #[pyo3(get)]
    pub keyframe_analysis_time_ms: f64,
    #[pyo3(get)]
    pub total_frames: usize,
    #[pyo3(get)]
    pub keyframes_extracted: usize,
    #[pyo3(get)]
    pub keyframe_ratio: f64,
    #[pyo3(get)]
    pub processing_fps: f64,
    #[pyo3(get)]
    pub threshold: f64,
    #[pyo3(get)]
    pub optimization_type: String,
    #[pyo3(get)]
    pub simd_enabled: bool,
    #[pyo3(get)]
    pub threads_used: usize,
    #[pyo3(get)]
    pub timestamp: String,
}

#[pymethods]
impl PyPerformanceResult {
    /// 转换为Python字典
    fn to_dict(&self) -> PyResult<HashMap<String, PyObject>> {
        Python::with_gil(|py| {
            let mut dict = HashMap::new();
            dict.insert("test_name".to_string(), self.test_name.to_object(py));
            dict.insert("video_file".to_string(), self.video_file.to_object(py));
            dict.insert("total_time_ms".to_string(), self.total_time_ms.to_object(py));
            dict.insert("frame_extraction_time_ms".to_string(), self.frame_extraction_time_ms.to_object(py));
            dict.insert("keyframe_analysis_time_ms".to_string(), self.keyframe_analysis_time_ms.to_object(py));
            dict.insert("total_frames".to_string(), self.total_frames.to_object(py));
            dict.insert("keyframes_extracted".to_string(), self.keyframes_extracted.to_object(py));
            dict.insert("keyframe_ratio".to_string(), self.keyframe_ratio.to_object(py));
            dict.insert("processing_fps".to_string(), self.processing_fps.to_object(py));
            dict.insert("threshold".to_string(), self.threshold.to_object(py));
            dict.insert("optimization_type".to_string(), self.optimization_type.to_object(py));
            dict.insert("simd_enabled".to_string(), self.simd_enabled.to_object(py));
            dict.insert("threads_used".to_string(), self.threads_used.to_object(py));
            dict.insert("timestamp".to_string(), self.timestamp.to_object(py));
            Ok(dict)
        })
    }
}

/// 主要的视频关键帧提取器类
#[pyclass]
pub struct VideoKeyframeExtractor {
    ffmpeg_path: String,
    threads: usize,
    verbose: bool,
}

#[pymethods]
impl VideoKeyframeExtractor {
    #[new]
    #[pyo3(signature = (ffmpeg_path = "ffmpeg".to_string(), threads = 0, verbose = false))]
    fn new(ffmpeg_path: String, threads: usize, verbose: bool) -> PyResult<Self> {
        // 设置线程池（如果还没有初始化）
        if threads > 0 {
            // 尝试设置线程池，如果已经初始化则忽略错误
            let _ = rayon::ThreadPoolBuilder::new()
                .num_threads(threads)
                .build_global();
        }
        
        Ok(Self {
            ffmpeg_path,
            threads: if threads == 0 { rayon::current_num_threads() } else { threads },
            verbose,
        })
    }
    
    /// 从视频中提取帧
    #[pyo3(signature = (video_path, max_frames=None))]
    fn extract_frames(&self, video_path: &str, max_frames: Option<usize>) -> PyResult<(Vec<PyVideoFrame>, usize, usize)> {
        let video_path = PathBuf::from(video_path);
        let max_frames = max_frames.unwrap_or(0);
        
        extract_frames_memory_stream(&video_path, &PathBuf::from(&self.ffmpeg_path), max_frames, self.verbose)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Frame extraction failed: {}", e)))
    }
    
    /// 提取关键帧索引
    #[pyo3(signature = (frames, threshold, use_simd=None, block_size=None))]
    fn extract_keyframes(
        &self, 
        frames: Vec<PyVideoFrame>, 
        threshold: f64, 
        use_simd: Option<bool>,
        block_size: Option<usize>
    ) -> PyResult<Vec<usize>> {
        let use_simd = use_simd.unwrap_or(true);
        let block_size = block_size.unwrap_or(8192);
        
        extract_keyframes_optimized(&frames, threshold, use_simd, block_size, self.verbose)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Keyframe extraction failed: {}", e)))
    }
    
    /// 保存关键帧为图片
    #[pyo3(signature = (video_path, keyframe_indices, output_dir, max_save=None))]
    fn save_keyframes(
        &self,
        video_path: &str,
        keyframe_indices: Vec<usize>,
        output_dir: &str,
        max_save: Option<usize>
    ) -> PyResult<usize> {
        let video_path = PathBuf::from(video_path);
        let output_dir = PathBuf::from(output_dir);
        let max_save = max_save.unwrap_or(50);
        
        save_keyframes_optimized(
            &video_path,
            &keyframe_indices,
            &output_dir,
            &PathBuf::from(&self.ffmpeg_path),
            max_save,
            self.verbose
        ).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Save keyframes failed: {}", e)))
    }
    
    /// 运行性能测试
    #[pyo3(signature = (video_path, threshold, test_name, max_frames=None, use_simd=None, block_size=None))]
    fn benchmark(
        &self,
        video_path: &str,
        threshold: f64,
        test_name: &str,
        max_frames: Option<usize>,
        use_simd: Option<bool>,
        block_size: Option<usize>
    ) -> PyResult<PyPerformanceResult> {
        let video_path = PathBuf::from(video_path);
        let max_frames = max_frames.unwrap_or(1000);
        let use_simd = use_simd.unwrap_or(true);
        let block_size = block_size.unwrap_or(8192);
        
        let result = run_performance_test(
            &video_path,
            threshold,
            test_name,
            &PathBuf::from(&self.ffmpeg_path),
            max_frames,
            use_simd,
            block_size,
            self.verbose
        ).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Benchmark failed: {}", e)))?;
        
        Ok(PyPerformanceResult {
            test_name: result.test_name,
            video_file: result.video_file,
            total_time_ms: result.total_time_ms,
            frame_extraction_time_ms: result.frame_extraction_time_ms,
            keyframe_analysis_time_ms: result.keyframe_analysis_time_ms,
            total_frames: result.total_frames,
            keyframes_extracted: result.keyframes_extracted,
            keyframe_ratio: result.keyframe_ratio,
            processing_fps: result.processing_fps,
            threshold: result.threshold,
            optimization_type: result.optimization_type,
            simd_enabled: result.simd_enabled,
            threads_used: result.threads_used,
            timestamp: result.timestamp,
        })
    }
    
    /// 完整的处理流程
    #[pyo3(signature = (video_path, output_dir, threshold=None, max_frames=None, max_save=None, use_simd=None, block_size=None))]
    fn process_video(
        &self,
        video_path: &str,
        output_dir: &str,
        threshold: Option<f64>,
        max_frames: Option<usize>,
        max_save: Option<usize>,
        use_simd: Option<bool>,
        block_size: Option<usize>
    ) -> PyResult<PyPerformanceResult> {
        let threshold = threshold.unwrap_or(2.0);
        let max_frames = max_frames.unwrap_or(0);
        let max_save = max_save.unwrap_or(50);
        let use_simd = use_simd.unwrap_or(true);
        let block_size = block_size.unwrap_or(8192);
        
        let video_path_buf = PathBuf::from(video_path);
        let output_dir_buf = PathBuf::from(output_dir);
        
        // 运行性能测试
        let result = run_performance_test(
            &video_path_buf,
            threshold,
            "Python Processing",
            &PathBuf::from(&self.ffmpeg_path),
            max_frames,
            use_simd,
            block_size,
            self.verbose
        ).map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Processing failed: {}", e)))?;
        
        // 提取并保存关键帧
        let (frames, _, _) = extract_frames_memory_stream(&video_path_buf, &PathBuf::from(&self.ffmpeg_path), max_frames, self.verbose)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Frame extraction failed: {}", e)))?;
        
        let frames: Vec<PyVideoFrame> = frames.into_iter().map(|f| PyVideoFrame {
            frame_number: f.frame_number,
            width: f.width,
            height: f.height,
            data: f.data,
        }).collect();
        
        let keyframe_indices = extract_keyframes_optimized(&frames, threshold, use_simd, block_size, self.verbose)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Keyframe extraction failed: {}", e)))?;
        
        save_keyframes_optimized(&video_path_buf, &keyframe_indices, &output_dir_buf, &PathBuf::from(&self.ffmpeg_path), max_save, self.verbose)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Save keyframes failed: {}", e)))?;
        
        Ok(PyPerformanceResult {
            test_name: result.test_name,
            video_file: result.video_file,
            total_time_ms: result.total_time_ms,
            frame_extraction_time_ms: result.frame_extraction_time_ms,
            keyframe_analysis_time_ms: result.keyframe_analysis_time_ms,
            total_frames: result.total_frames,
            keyframes_extracted: result.keyframes_extracted,
            keyframe_ratio: result.keyframe_ratio,
            processing_fps: result.processing_fps,
            threshold: result.threshold,
            optimization_type: result.optimization_type,
            simd_enabled: result.simd_enabled,
            threads_used: result.threads_used,
            timestamp: result.timestamp,
        })
    }
    
    /// 获取CPU特性信息
    fn get_cpu_features(&self) -> PyResult<HashMap<String, bool>> {
        let mut features = HashMap::new();
        
        #[cfg(target_arch = "x86_64")]
        {
            features.insert("avx2".to_string(), std::arch::is_x86_feature_detected!("avx2"));
            features.insert("sse2".to_string(), std::arch::is_x86_feature_detected!("sse2"));
            features.insert("sse4_1".to_string(), std::arch::is_x86_feature_detected!("sse4.1"));
            features.insert("sse4_2".to_string(), std::arch::is_x86_feature_detected!("sse4.2"));
            features.insert("fma".to_string(), std::arch::is_x86_feature_detected!("fma"));
        }
        
        #[cfg(not(target_arch = "x86_64"))]
        {
            features.insert("simd_supported".to_string(), false);
        }
        
        Ok(features)
    }
    
    /// 获取当前使用的线程数
    fn get_thread_count(&self) -> usize {
        self.threads
    }
    
    /// 获取配置的线程数
    fn get_configured_threads(&self) -> usize {
        self.threads
    }
    
    /// 获取实际运行的线程数
    fn get_actual_thread_count(&self) -> usize {
        rayon::current_num_threads()
    }
}

// 从main.rs中复制的核心函数

struct PerformanceResult {
    test_name: String,
    video_file: String,
    total_time_ms: f64,
    frame_extraction_time_ms: f64,
    keyframe_analysis_time_ms: f64,
    total_frames: usize,
    keyframes_extracted: usize,
    keyframe_ratio: f64,
    processing_fps: f64,
    threshold: f64,
    optimization_type: String,
    simd_enabled: bool,
    threads_used: usize,
    timestamp: String,
}

fn extract_frames_memory_stream(
    video_path: &PathBuf,
    ffmpeg_path: &PathBuf,
    max_frames: usize,
    verbose: bool,
) -> Result<(Vec<PyVideoFrame>, usize, usize)> {
    if verbose {
        println!("🎬 Extracting frames using FFmpeg memory streaming...");
        println!("📁 Video: {}", video_path.display());
    }
    
    // 获取视频信息
    let probe_output = Command::new(ffmpeg_path)
        .args(["-i", video_path.to_str().unwrap(), "-hide_banner"])
        .output()
        .context("Failed to probe video with FFmpeg")?;
    
    let probe_info = String::from_utf8_lossy(&probe_output.stderr);
    let (width, height) = parse_video_dimensions(&probe_info)
        .ok_or_else(|| anyhow::anyhow!("Cannot parse video dimensions"))?;
    
    if verbose {
        println!("📐 Video dimensions: {}x{}", width, height);
    }
    
    // 构建优化的FFmpeg命令
    let mut cmd = Command::new(ffmpeg_path);
    cmd.args([
        "-i", video_path.to_str().unwrap(),
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "-an",
        "-threads", "0",
        "-preset", "ultrafast",
    ]);
    
    if max_frames > 0 {
        cmd.args(["-frames:v", &max_frames.to_string()]);
    }
    
    cmd.args(["-"]).stdout(Stdio::piped()).stderr(Stdio::null());
    
    let start_time = Instant::now();
    let mut child = cmd.spawn().context("Failed to spawn FFmpeg process")?;
    let stdout = child.stdout.take().unwrap();
    let mut reader = BufReader::with_capacity(1024 * 1024, stdout);
    
    let frame_size = width * height;
    let mut frames = Vec::new();
    let mut frame_count = 0;
    let mut frame_buffer = vec![0u8; frame_size];
    
    if verbose {
        println!("📦 Frame size: {} bytes", frame_size);
    }
    
    // 直接流式读取帧数据到内存
    loop {
        match reader.read_exact(&mut frame_buffer) {
            Ok(()) => {
                frames.push(PyVideoFrame::new(
                    frame_count,
                    width,
                    height,
                    frame_buffer.clone(),
                ));
                frame_count += 1;
                
                if verbose && frame_count % 200 == 0 {
                    print!("\r⚡ Frames processed: {}", frame_count);
                }
                
                if max_frames > 0 && frame_count >= max_frames {
                    break;
                }
            }
            Err(_) => break,
        }
    }
    
    let _ = child.wait();
    
    if verbose {
        println!("\r✅ Frame extraction complete: {} frames in {:.2}s", 
                frame_count, start_time.elapsed().as_secs_f64());
    }
    
    Ok((frames, width, height))
}

fn parse_video_dimensions(probe_info: &str) -> Option<(usize, usize)> {
    for line in probe_info.lines() {
        if line.contains("Video:") && line.contains("x") {
            for part in line.split_whitespace() {
                if let Some(x_pos) = part.find('x') {
                    let width_str = &part[..x_pos];
                    let height_part = &part[x_pos + 1..];
                    let height_str = height_part.split(',').next().unwrap_or(height_part);
                    
                    if let (Ok(width), Ok(height)) = (width_str.parse::<usize>(), height_str.parse::<usize>()) {
                        return Some((width, height));
                    }
                }
            }
        }
    }
    None
}

fn extract_keyframes_optimized(
    frames: &[PyVideoFrame],
    threshold: f64,
    use_simd: bool,
    block_size: usize,
    verbose: bool,
) -> Result<Vec<usize>> {
    if frames.len() < 2 {
        return Ok(Vec::new());
    }
    
    let optimization_name = if use_simd { "SIMD+Parallel" } else { "Standard Parallel" };
    if verbose {
        println!("🚀 Keyframe analysis (threshold: {}, optimization: {})", threshold, optimization_name);
    }
    
    let start_time = Instant::now();
    
    // 并行计算帧差异
    let differences: Vec<f64> = frames
        .par_windows(2)
        .map(|pair| {
            if use_simd {
                pair[0].calculate_difference_parallel_simd(&pair[1], block_size, true)
            } else {
                pair[0].calculate_difference(&pair[1]).unwrap_or(f64::MAX)
            }
        })
        .collect();
    
    // 基于阈值查找关键帧
    let keyframe_indices: Vec<usize> = differences
        .par_iter()
        .enumerate()
        .filter_map(|(i, &diff)| {
            if diff > threshold {
                Some(i + 1)
            } else {
                None
            }
        })
        .collect();
    
    if verbose {
        println!("⚡ Analysis complete in {:.2}s", start_time.elapsed().as_secs_f64());
        println!("🎯 Found {} keyframes", keyframe_indices.len());
    }
    
    Ok(keyframe_indices)
}

fn save_keyframes_optimized(
    video_path: &PathBuf,
    keyframe_indices: &[usize],
    output_dir: &PathBuf,
    ffmpeg_path: &PathBuf,
    max_save: usize,
    verbose: bool,
) -> Result<usize> {
    if keyframe_indices.is_empty() {
        if verbose {
            println!("⚠️  No keyframes to save");
        }
        return Ok(0);
    }
    
    if verbose {
        println!("💾 Saving keyframes...");
    }
    
    fs::create_dir_all(output_dir).context("Failed to create output directory")?;
    
    let save_count = keyframe_indices.len().min(max_save);
    let mut saved = 0;
    
    for (i, &frame_idx) in keyframe_indices.iter().take(save_count).enumerate() {
        let output_path = output_dir.join(format!("keyframe_{:03}.jpg", i + 1));
        let timestamp = frame_idx as f64 / 30.0; // 假设30 FPS
        
        let output = Command::new(ffmpeg_path)
            .args([
                "-i", video_path.to_str().unwrap(),
                "-ss", &timestamp.to_string(),
                "-vframes", "1",
                "-q:v", "2",
                "-y",
                output_path.to_str().unwrap(),
            ])
            .output()
            .context("Failed to extract keyframe with FFmpeg")?;
        
        if output.status.success() {
            saved += 1;
            if verbose && (saved % 10 == 0 || saved == save_count) {
                print!("\r💾 Saved: {}/{} keyframes", saved, save_count);
            }
        } else if verbose {
            eprintln!("⚠️  Failed to save keyframe {}", frame_idx);
        }
    }
    
    if verbose {
        println!("\r✅ Keyframe saving complete: {}/{}", saved, save_count);
    }
    
    Ok(saved)
}

fn run_performance_test(
    video_path: &PathBuf,
    threshold: f64,
    test_name: &str,
    ffmpeg_path: &PathBuf,
    max_frames: usize,
    use_simd: bool,
    block_size: usize,
    verbose: bool,
) -> Result<PerformanceResult> {
    if verbose {
        println!("\n{}", "=".repeat(60));
        println!("⚡ Running test: {}", test_name);
        println!("{}", "=".repeat(60));
    }
    
    let total_start = Instant::now();
    
    // 帧提取
    let extraction_start = Instant::now();
    let (frames, _width, _height) = extract_frames_memory_stream(video_path, ffmpeg_path, max_frames, verbose)?;
    let extraction_time = extraction_start.elapsed().as_secs_f64() * 1000.0;
    
    // 关键帧分析
    let analysis_start = Instant::now();
    let keyframe_indices = extract_keyframes_optimized(&frames, threshold, use_simd, block_size, verbose)?;
    let analysis_time = analysis_start.elapsed().as_secs_f64() * 1000.0;
    
    let total_time = total_start.elapsed().as_secs_f64() * 1000.0;
    
    let optimization_type = if use_simd { 
        format!("SIMD+Parallel(block:{})", block_size) 
    } else { 
        "Standard Parallel".to_string() 
    };
    
    let result = PerformanceResult {
        test_name: test_name.to_string(),
        video_file: video_path.file_name().unwrap().to_string_lossy().to_string(),
        total_time_ms: total_time,
        frame_extraction_time_ms: extraction_time,
        keyframe_analysis_time_ms: analysis_time,
        total_frames: frames.len(),
        keyframes_extracted: keyframe_indices.len(),
        keyframe_ratio: keyframe_indices.len() as f64 / frames.len() as f64 * 100.0,
        processing_fps: frames.len() as f64 / (total_time / 1000.0),
        threshold,
        optimization_type,
        simd_enabled: use_simd,
        threads_used: rayon::current_num_threads(),
        timestamp: Local::now().format("%Y-%m-%d %H:%M:%S").to_string(),
    };
    
    if verbose {
        println!("\n⚡ Test Results:");
        println!("  🕐 Total time: {:.2}ms ({:.2}s)", result.total_time_ms, result.total_time_ms / 1000.0);
        println!("  📥 Extraction: {:.2}ms ({:.1}%)", result.frame_extraction_time_ms, 
                 result.frame_extraction_time_ms / result.total_time_ms * 100.0);
        println!("  🧮 Analysis: {:.2}ms ({:.1}%)", result.keyframe_analysis_time_ms,
                 result.keyframe_analysis_time_ms / result.total_time_ms * 100.0);
        println!("  📊 Frames: {}", result.total_frames);
        println!("  🎯 Keyframes: {}", result.keyframes_extracted);
        println!("  🚀 Speed: {:.1} FPS", result.processing_fps);
        println!("  ⚙️  Optimization: {}", result.optimization_type);
    }
    
    Ok(result)
}

/// Python模块定义
#[pymodule]
fn rust_video(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyVideoFrame>()?;
    m.add_class::<PyPerformanceResult>()?;
    m.add_class::<VideoKeyframeExtractor>()?;
    
    // 便捷函数
    #[pyfn(m)]
    #[pyo3(signature = (video_path, output_dir, threshold=None, max_frames=None, max_save=None, ffmpeg_path=None, use_simd=None, threads=None, verbose=None))]
    fn extract_keyframes_from_video(
        video_path: &str,
        output_dir: &str,
        threshold: Option<f64>,
        max_frames: Option<usize>,
        max_save: Option<usize>,
        ffmpeg_path: Option<String>,
        use_simd: Option<bool>,
        threads: Option<usize>,
        verbose: Option<bool>
    ) -> PyResult<PyPerformanceResult> {
        let extractor = VideoKeyframeExtractor::new(
            ffmpeg_path.unwrap_or_else(|| "ffmpeg".to_string()),
            threads.unwrap_or(0),
            verbose.unwrap_or(false)
        )?;
        
        extractor.process_video(
            video_path,
            output_dir,
            threshold,
            max_frames,
            max_save,
            use_simd,
            None
        )
    }
    
    #[pyfn(m)]
    fn get_system_info() -> PyResult<HashMap<String, PyObject>> {
        Python::with_gil(|py| {
            let mut info = HashMap::new();
            info.insert("threads".to_string(), rayon::current_num_threads().to_object(py));
            
            #[cfg(target_arch = "x86_64")]
            {
                info.insert("avx2_supported".to_string(), std::arch::is_x86_feature_detected!("avx2").to_object(py));
                info.insert("sse2_supported".to_string(), std::arch::is_x86_feature_detected!("sse2").to_object(py));
            }
            
            #[cfg(not(target_arch = "x86_64"))]
            {
                info.insert("simd_supported".to_string(), false.to_object(py));
            }
            
            info.insert("version".to_string(), "0.1.0".to_object(py));
            
            Ok(info)
        })
    }
    
    Ok(())
}
