use super::*;

#[derive(Debug)]
pub(crate) struct ShadowReportHistoryCell {
    shadow_name: String,
    content: String,
}

impl ShadowReportHistoryCell {
    pub(crate) fn new(shadow_name: String, content: String) -> Self {
        Self {
            shadow_name,
            content,
        }
    }
}

pub(crate) fn new_shadow_report(shadow_name: String, content: String) -> ShadowReportHistoryCell {
    ShadowReportHistoryCell::new(shadow_name, content)
}

impl HistoryCell for ShadowReportHistoryCell {
    fn display_lines(&self, width: u16) -> Vec<Line<'static>> {
        let mut lines = vec![
            vec![
                "Shadow".magenta().bold(),
                " · ".dim(),
                self.shadow_name.clone().magenta().bold(),
            ]
            .into(),
        ];
        let wrap_width = width.saturating_sub(2).max(1) as usize;
        let body = self
            .content
            .lines()
            .map(|line| Line::from(line.to_string().dim()))
            .collect::<Vec<_>>();
        let wrapped = adaptive_wrap_lines(
            &body,
            RtOptions::new(wrap_width)
                .initial_indent("  ".into())
                .subsequent_indent("  ".into()),
        );
        push_owned_lines(&wrapped, &mut lines);
        lines
    }

    fn raw_lines(&self) -> Vec<Line<'static>> {
        std::iter::once(Line::from(format!("Shadow · {}", self.shadow_name)))
            .chain(self.content.lines().map(|line| Line::from(line.to_owned())))
            .collect()
    }
}
