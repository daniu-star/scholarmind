/**
 * ScholarMind 写作检测规则引擎
 * 提供实时写作检测，包括字数统计、结构分析、语法检查、学术规范检测、写作建议
 */

/**
 * 主入口：检测写作内容
 * @param {string} content 写作内容（Markdown）
 * @returns {Object} 检测结果
 */
export function checkWriting(content) {
  if (!content || typeof content !== 'string') content = '';
  return {
    wordCount: countWords(content),
    structure: analyzeStructure(content),
    grammar: checkGrammar(content),
    academic: checkAcademicNorms(content),
    suggestions: generateSuggestions(content),
  };
}

/**
 * 字数统计
 * - 中文字数：统计所有中文字符
 * - 英文字数：按空白分隔的英文单词数
 * - 段落数：以空行分隔的非空段落数
 */
export function countWords(content) {
  if (!content) {
    return { total: 0, chinese: 0, english: 0, paragraphs: 0 };
  }
  // 中文字符（含全角标点不计入字数）
  const chineseChars = content.match(/[\u4e00-\u9fa5]/g) || [];
  const chinese = chineseChars.length;

  // 英文单词（去除 Markdown 标记后按空白分隔）
  const stripped = stripMarkdown(content);
  const englishWords = stripped.match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g) || [];
  const english = englishWords.length;

  // 段落数：以空行分隔
  const paragraphs = countParagraphs(content);

  // 总字数：中文字符数 + 英文单词数（粗略等价）
  const total = chinese + english;

  return { total, chinese, english, paragraphs };
}

/**
 * 结构分析：检测 Markdown 标题层级与段落分布
 */
export function analyzeStructure(content) {
  if (!content) {
    return { headings: [], paragraphCount: 0, avgParagraphLength: 0 };
  }
  const lines = content.split('\n');
  const headings = [];
  lines.forEach((line, idx) => {
    const m = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (m) {
      headings.push({
        level: m[1].length,
        text: m[2].trim(),
        line: idx + 1,
      });
    }
  });

  // 段落统计（排除标题、空行、引用等）
  const paragraphs = content
    .split(/\n\s*\n/)
    .map(p => p.trim())
    .filter(p => p && !/^#{1,6}\s/.test(p));

  const paragraphCount = paragraphs.length;
  const totalLen = paragraphs.reduce((sum, p) => sum + stripMarkdown(p).length, 0);
  const avgParagraphLength = paragraphCount > 0 ? Math.round(totalLen / paragraphCount) : 0;

  return { headings, paragraphCount, avgParagraphLength };
}

/**
 * 基础语法检查
 * - 重复标点（如 。。。、！！！）
 * - 多余空格（如中文字符间的多个空格）
 * - 中英文混排空格（中文与英文/数字之间未加空格）
 */
export function checkGrammar(content) {
  const issues = [];
  if (!content) return { issues };

  const lines = content.split('\n');
  lines.forEach((line, idx) => {
    const lineNum = idx + 1;

    // 1. 重复标点（3个及以上相同标点）
    const dupPunct = line.match(/([。，！？；：、,.!?;:])\1{2,}/g);
    if (dupPunct) {
      dupPunct.forEach(m => {
        issues.push({
          type: 'duplicate_punctuation',
          message: `重复标点 "${m}"`,
          position: `第${lineNum}行`,
        });
      });
    }

    // 2. 行尾多余空格
    if (/[ \t]+$/.test(line)) {
      issues.push({
        type: 'trailing_whitespace',
        message: '行尾存在多余空格',
        position: `第${lineNum}行`,
      });
    }

    // 3. 中文字符间多个空格
    const cnMultiSpace = line.match(/[\u4e00-\u9fa5][ \t]{2,}[\u4e00-\u9fa5]/g);
    if (cnMultiSpace) {
      issues.push({
        type: 'redundant_space',
        message: '中文字符间存在多余空格',
        position: `第${lineNum}行`,
      });
    }

    // 4. 中文标点后跟英文标点（如 ，. 或 。,）
    const mixedPunct = line.match(/[，。！？；：][,.!?;:]/g);
    if (mixedPunct) {
      issues.push({
        type: 'mixed_punctuation',
        message: '中英文标点混用',
        position: `第${lineNum}行`,
      });
    }
  });

  // 5. 中英文混排：中文与英文/数字之间建议加空格（仅作提示）
  // 这里只检测明显遗漏（连续中文+英文，无空格），且不重复报告
  const noSpaceMix = content.match(/[\u4e00-\u9fa5][A-Za-z0-9]/g) || [];
  const noSpaceMix2 = content.match(/[A-Za-z0-9][\u4e00-\u9fa5]/g) || [];
  const mixCount = noSpaceMix.length + noSpaceMix2.length;
  if (mixCount > 0) {
    issues.push({
      type: 'cn_en_spacing',
      message: `中英文混排未加空格（共 ${mixCount} 处），建议在中文与英文/数字之间添加空格`,
      position: '全文',
    });
  }

  return { issues };
}

/**
 * 学术规范检测
 * - 引用格式（GB/T 7714）：检测 [1]、[2] 等引用标记
 * - 参考文献完整性：检测是否存在 "## 参考文献" 等章节
 */
export function checkAcademicNorms(content) {
  const citations = [];
  const issues = [];
  let hasReferences = false;

  if (!content) {
    return { citations, hasReferences, issues };
  }

  // 1. 检测引用标记 [1]、[1,2]、[1-3] 等
  const citationRegex = /\[(\d+(?:\s*[-,，]\s*\d+)*)\]/g;
  let m;
  while ((m = citationRegex.exec(content)) !== null) {
    // 解析引用编号
    const raw = m[1];
    const nums = [];
    raw.split(/[-,，]/).forEach(part => {
      const n = parseInt(part.trim(), 10);
      if (!isNaN(n)) nums.push(n);
    });
    citations.push({
      raw: m[0],
      numbers: nums,
      index: m.index,
    });
  }

  // 2. 检测参考文献章节
  const refSectionRegex = /^#{1,6}\s*(参考文献|References|REFERENCES|文献|Bibliography)\s*#*\s*$/im;
  hasReferences = refSectionRegex.test(content);

  // 3. 检测参考文献条目格式（GB/T 7714 简化版）
  //    [1] 作者. 标题[J/M/D/C]. 期刊, 年份.
  if (hasReferences) {
    const refMatch = content.match(/#{1,6}\s*(?:参考文献|References|REFERENCES|文献|Bibliography)\s*#*\s*\n([\s\S]*?)$/im);
    if (refMatch) {
      const refSection = refMatch[1];
      const refLines = refSection.split('\n').map(l => l.trim()).filter(l => l);
      const refEntries = refLines.filter(l => /^\[\d+\]/.test(l));
      if (refEntries.length === 0) {
        issues.push('参考文献章节未检测到标准条目（应以 [1] 等编号开头）');
      } else {
        // 检测条目类型标记
        const typeMarkRegex = /\[(J|M|D|C|N|R|S|P|EB\/OL|J\/OL)\]/;
        const noTypeEntries = refEntries.filter(e => !typeMarkRegex.test(e));
        if (noTypeEntries.length > 0) {
          issues.push(`${noTypeEntries.length} 条参考文献缺少文献类型标识（如 [J]、[M]、[D] 等）`);
        }
      }
    }
  } else {
    if (citations.length > 0) {
      issues.push('检测到引用标记，但未找到参考文献章节');
    }
  }

  // 4. 引用编号连续性检查
  if (citations.length > 0) {
    const allNums = [];
    citations.forEach(c => allNums.push(...c.numbers));
    const uniqueNums = [...new Set(allNums)].sort((a, b) => a - b);
    if (uniqueNums.length > 0) {
      const max = uniqueNums[uniqueNums.length - 1];
      const missing = [];
      for (let i = 1; i <= max; i++) {
        if (!uniqueNums.includes(i)) missing.push(i);
      }
      if (missing.length > 0 && missing.length <= 20) {
        issues.push(`引用编号不连续，缺失：${missing.join(', ')}`);
      }
    }
  }

  return { citations, hasReferences, issues };
}

/**
 * 基于规则的写作建议
 */
export function generateSuggestions(content) {
  const suggestions = [];
  if (!content) {
    suggestions.push('内容为空，请开始撰写你的学术论文');
    return suggestions;
  }

  const structure = analyzeStructure(content);
  const wordCount = countWords(content);
  const academic = checkAcademicNorms(content);

  // 1. 标题层级
  if (structure.headings.length === 0) {
    suggestions.push('未检测到标题，建议使用 Markdown 标题（#、##、###）组织文档结构');
  } else {
    // 检查是否跳级（如 # 直接到 ###）
    const levels = structure.headings.map(h => h.level);
    for (let i = 1; i < levels.length; i++) {
      if (levels[i] > levels[i - 1] + 1) {
        suggestions.push(`标题层级跳级：从 H${levels[i - 1]} 直接到 H${levels[i]}，建议层级递进`);
        break;
      }
    }
    // 检查是否缺少一级标题
    if (!levels.includes(1)) {
      suggestions.push('未检测到一级标题（#），建议添加论文主标题');
    }
  }

  // 2. 段落过长
  const paragraphs = content
    .split(/\n\s*\n/)
    .map(p => p.trim())
    .filter(p => p && !/^#{1,6}\s/.test(p));
  paragraphs.forEach((p, i) => {
    const len = stripMarkdown(p).length;
    if (len > 500) {
      suggestions.push(`第 ${i + 1} 段较长（${len} 字），建议拆分为多个段落以提升可读性`);
    }
  });

  // 3. 字数检查
  if (wordCount.total > 0 && wordCount.total < 200) {
    suggestions.push('当前内容较短，学术论文通常需要更充分的论述');
  }

  // 4. 引用检查
  if (academic.citations.length === 0 && wordCount.total > 300) {
    suggestions.push('未检测到引用标记，学术论文应包含充分的文献引用（如 [1]）');
  }
  if (academic.citations.length > 0 && !academic.hasReferences) {
    suggestions.push('存在引用标记但缺少参考文献章节，请添加 "## 参考文献" 部分');
  }

  // 5. 参考文献条目数与引用数的匹配
  if (academic.hasReferences && academic.citations.length > 0) {
    const citedNums = new Set();
    academic.citations.forEach(c => c.numbers.forEach(n => citedNums.add(n)));
    const maxCited = citedNums.size > 0 ? Math.max(...citedNums) : 0;
    if (maxCited > 0) {
      // 简单提示，不强制要求精确匹配
    }
  }

  // 6. 检测是否包含摘要、关键词等学术要素
  const hasAbstract = /(^|\n)\s*#{1,6}\s*(摘要|Abstract|ABSTRACT)\b/.test(content);
  const hasKeywords = /关键词|Keywords|KEYWORDS/.test(content);
  if (wordCount.total > 500) {
    if (!hasAbstract) {
      suggestions.push('未检测到"摘要"章节，学术论文通常需要包含摘要');
    }
    if (!hasKeywords) {
      suggestions.push('未检测到"关键词"，建议在摘要后列出 3-5 个关键词');
    }
  }

  return suggestions;
}

// ========== 辅助函数 ==========

/**
 * 去除 Markdown 标记，返回纯文本
 */
function stripMarkdown(content) {
  if (!content) return '';
  return content
    // 去除标题标记
    .replace(/^#{1,6}\s+/gm, '')
    // 去除粗体/斜体
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    // 去除行内代码
    .replace(/`([^`]+)`/g, '$1')
    // 去除代码块
    .replace(/```[\s\S]*?```/g, '')
    // 去除链接，保留文本
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // 去除图片
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    // 去除引用标记
    .replace(/^>\s+/gm, '')
    // 去除列表标记
    .replace(/^[\s]*[-*+]\s+/gm, '')
    .replace(/^[\s]*\d+\.\s+/gm, '')
    // 去除水平分割线
    .replace(/^[-*_]{3,}$/gm, '')
    // 去除引用编号 [1]
    .replace(/\[\d+(?:[-,，\s*\d]+)*\]/g, '')
    .trim();
}

/**
 * 计算段落数（以空行分隔的非空段落）
 */
function countParagraphs(content) {
  if (!content) return 0;
  return content
    .split(/\n\s*\n/)
    .map(p => p.trim())
    .filter(p => p.length > 0)
    .length;
}
