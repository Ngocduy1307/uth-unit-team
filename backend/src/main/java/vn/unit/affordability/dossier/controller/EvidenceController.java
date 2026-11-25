package vn.unit.affordability.dossier.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import vn.unit.affordability.dossier.dto.CreateEvidenceRequest;
import vn.unit.affordability.dossier.dto.EvidenceOcrResultResponse;
import vn.unit.affordability.dossier.dto.EvidenceRecordResponse;
import vn.unit.affordability.dossier.dto.SubmitOcrResultRequest;
import vn.unit.affordability.dossier.service.EvidenceService;
import vn.unit.affordability.shared.dto.ApiResponse;

import java.util.List;

@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
@Tag(name = "Evidence & OCR", description = "Tiếp nhận chứng từ, quản lý phiên bản và lưu trữ kết quả OCR")
public class EvidenceController {

    private final EvidenceService evidenceService;

    @PostMapping("/dossiers/{dossierId}/evidences")
    @Operation(summary = "Đăng ký tiếp nhận chứng từ mới (tự động tăng version theo fileType)")
    public ResponseEntity<ApiResponse<EvidenceRecordResponse>> registerEvidence(
            @PathVariable String dossierId,
            @Valid @RequestBody CreateEvidenceRequest request) {
        EvidenceRecordResponse response = evidenceService.registerEvidence(dossierId, request);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success("Evidence registered successfully", response));
    }

    @GetMapping("/dossiers/{dossierId}/evidences")
    @Operation(summary = "Lấy danh sách chứng từ của hồ sơ")
    public ResponseEntity<ApiResponse<List<EvidenceRecordResponse>>> getEvidencesByDossier(
            @PathVariable String dossierId,
            @RequestParam(defaultValue = "false") boolean latestOnly) {
        return ResponseEntity.ok(ApiResponse.success(
                evidenceService.getEvidencesByDossierId(dossierId, latestOnly)));
    }

    @GetMapping("/evidences/{evidenceId}")
    @Operation(summary = "Lấy chi tiết chứng từ theo ID")
    public ResponseEntity<ApiResponse<EvidenceRecordResponse>> getEvidenceById(
            @PathVariable String evidenceId) {
        return ResponseEntity.ok(ApiResponse.success(
                evidenceService.getEvidenceById(evidenceId)));
    }

    @PostMapping("/evidences/{evidenceId}/ocr-results")
    @Operation(summary = "Tiếp nhận và lưu trữ kết quả OCR cho chứng từ (tự động tăng ocrVersion)")
    public ResponseEntity<ApiResponse<EvidenceOcrResultResponse>> submitOcrResult(
            @PathVariable String evidenceId,
            @Valid @RequestBody SubmitOcrResultRequest request) {
        EvidenceOcrResultResponse response = evidenceService.submitOcrResult(evidenceId, request);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success("OCR result saved successfully", response));
    }

    @GetMapping("/evidences/{evidenceId}/ocr-results")
    @Operation(summary = "Truy xuất toàn bộ lịch sử phiên bản kết quả OCR của chứng từ")
    public ResponseEntity<ApiResponse<List<EvidenceOcrResultResponse>>> getOcrResults(
            @PathVariable String evidenceId) {
        return ResponseEntity.ok(ApiResponse.success(
                evidenceService.getOcrResultsByEvidenceId(evidenceId)));
    }

    @GetMapping("/evidences/{evidenceId}/ocr-results/latest")
    @Operation(summary = "Truy xuất kết quả OCR mới nhất của chứng từ")
    public ResponseEntity<ApiResponse<EvidenceOcrResultResponse>> getLatestOcrResult(
            @PathVariable String evidenceId) {
        return ResponseEntity.ok(ApiResponse.success(
                evidenceService.getLatestOcrResult(evidenceId)));
    }
}
