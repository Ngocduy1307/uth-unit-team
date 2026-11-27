package vn.unit.affordability.dossier.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import vn.unit.affordability.dossier.dto.CreateEvidenceRequest;
import vn.unit.affordability.dossier.dto.EvidenceOcrResultResponse;
import vn.unit.affordability.dossier.dto.EvidenceRecordResponse;
import vn.unit.affordability.dossier.dto.SubmitOcrResultRequest;
import vn.unit.affordability.dossier.model.EvidenceOcrResult;
import vn.unit.affordability.dossier.model.EvidenceRecord;
import vn.unit.affordability.dossier.repository.DossierRepository;
import vn.unit.affordability.dossier.repository.EvidenceOcrResultRepository;
import vn.unit.affordability.dossier.repository.EvidenceRecordRepository;
import vn.unit.affordability.dossier.service.EvidenceService;
import vn.unit.affordability.shared.audit.model.AuditLog;
import vn.unit.affordability.shared.audit.repository.AuditLogRepository;
import vn.unit.affordability.shared.exception.BusinessValidationException;
import vn.unit.affordability.shared.exception.ResourceNotFoundException;
import vn.unit.affordability.shared.outbox.model.OutboxEvent;
import vn.unit.affordability.shared.outbox.repository.OutboxEventRepository;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class EvidenceServiceImpl implements EvidenceService {

    private final EvidenceRecordRepository evidenceRecordRepository;
    private final EvidenceOcrResultRepository ocrResultRepository;
    private final DossierRepository dossierRepository;
    private final AuditLogRepository auditLogRepository;
    private final OutboxEventRepository outboxEventRepository;
    private final ObjectMapper objectMapper;

    @Override
    @Transactional
    public EvidenceRecordResponse registerEvidence(String dossierId, CreateEvidenceRequest request) {
        if (!dossierRepository.existsById(dossierId)) {
            throw new ResourceNotFoundException("Dossier not found: " + dossierId);
        }

        String normalizedHash = request.getFileHash().toLowerCase();
        if (evidenceRecordRepository.findByDossierIdAndFileHash(dossierId, normalizedHash).isPresent()) {
            throw new BusinessValidationException("Duplicate evidence file hash in dossier: " + normalizedHash);
        }

        List<EvidenceRecord> existingByType = evidenceRecordRepository
                .findByDossierIdAndFileTypeOrderByVersionDesc(dossierId, request.getFileType());

        int nextVersion = existingByType.isEmpty() ? 1 : existingByType.get(0).getVersion() + 1;

        for (EvidenceRecord previous : existingByType) {
            if (Boolean.TRUE.equals(previous.getIsLatest())) {
                previous.setIsLatest(false);
                previous.setUpdatedBy(request.getUploadedBy());
                evidenceRecordRepository.save(previous);
            }
        }

        String evidenceId = UUID.randomUUID().toString();
        EvidenceRecord record = EvidenceRecord.builder()
                .id(evidenceId)
                .dossierId(dossierId)
                .fileName(request.getFileName())
                .fileHash(normalizedHash)
                .fileType(request.getFileType())
                .storagePath(request.getStoragePath())
                .status("RECEIVED")
                .uploadedBy(request.getUploadedBy())
                .fileSizeBytes(request.getFileSizeBytes())
                .mimeType(request.getMimeType())
                .ocrStatus("PENDING")
                .version(nextVersion)
                .isLatest(true)
                .updatedBy(request.getUploadedBy())
                .build();

        EvidenceRecord saved = evidenceRecordRepository.save(record);

        recordAudit(
                dossierId,
                "EVIDENCE",
                evidenceId,
                "CREATE",
                "version",
                existingByType.isEmpty() ? null : "v" + existingByType.get(0).getVersion(),
                request.getFileName() + " (v" + nextVersion + ")",
                request.getUploadedBy(),
                "MAKER",
                request.getReason() != null ? request.getReason() : "Upload evidence document"
        );

        emitOutboxEvent(
                "EVIDENCE",
                evidenceId,
                "EVIDENCE_RECEIVED",
                Map.of(
                        "evidenceId", evidenceId,
                        "dossierId", dossierId,
                        "fileType", saved.getFileType(),
                        "fileHash", saved.getFileHash(),
                        "version", saved.getVersion()
                )
        );

        return toEvidenceResponse(saved);
    }

    @Override
    public List<EvidenceRecordResponse> getEvidencesByDossierId(String dossierId, boolean latestOnly) {
        if (!dossierRepository.existsById(dossierId)) {
            throw new ResourceNotFoundException("Dossier not found: " + dossierId);
        }
        List<EvidenceRecord> records = latestOnly
                ? evidenceRecordRepository.findByDossierIdAndIsLatestTrueOrderByCreatedAtDesc(dossierId)
                : evidenceRecordRepository.findByDossierIdOrderByCreatedAtDesc(dossierId);

        return records.stream()
                .map(this::toEvidenceResponse)
                .toList();
    }

    @Override
    public EvidenceRecordResponse getEvidenceById(String evidenceId) {
        return evidenceRecordRepository.findById(evidenceId)
                .map(this::toEvidenceResponse)
                .orElseThrow(() -> new ResourceNotFoundException("Evidence not found: " + evidenceId));
    }

    @Override
    @Transactional
    public EvidenceOcrResultResponse submitOcrResult(String evidenceId, SubmitOcrResultRequest request) {
        EvidenceRecord evidence = evidenceRecordRepository.findById(evidenceId)
                .orElseThrow(() -> new ResourceNotFoundException("Evidence not found: " + evidenceId));

        validateJson(request.getRawPayload(), "rawPayload");
        if (request.getExtractedSummary() != null && !request.getExtractedSummary().isBlank()) {
            validateJson(request.getExtractedSummary(), "extractedSummary");
        }

        int nextOcrVersion = ocrResultRepository.findFirstByEvidenceIdOrderByOcrVersionDesc(evidenceId)
                .map(existing -> existing.getOcrVersion() + 1)
                .orElse(1);

        OffsetDateTime processedAt = OffsetDateTime.now();
        String ocrResultId = UUID.randomUUID().toString();

        EvidenceOcrResult ocrResult = EvidenceOcrResult.builder()
                .id(ocrResultId)
                .evidenceId(evidenceId)
                .dossierId(evidence.getDossierId())
                .ocrVersion(nextOcrVersion)
                .engineName(request.getEngineName())
                .engineVersion(request.getEngineVersion())
                .confidenceScore(request.getConfidenceScore())
                .rawPayload(request.getRawPayload())
                .extractedSummary(request.getExtractedSummary())
                .status(request.getStatus())
                .errorMessage(request.getErrorMessage())
                .processedBy(request.getProcessedBy())
                .processedAt(processedAt)
                .build();

        EvidenceOcrResult savedOcr = ocrResultRepository.save(ocrResult);

        String previousOcrStatus = evidence.getOcrStatus();
        evidence.setOcrStatus(request.getStatus());
        evidence.setOcrProcessedAt(processedAt);
        evidence.setStatus("COMPLETED".equals(request.getStatus()) ? "EXTRACTED" : "FAILED");
        evidence.setUpdatedBy(request.getProcessedBy());
        evidenceRecordRepository.save(evidence);

        recordAudit(
                evidence.getDossierId(),
                "EVIDENCE_OCR",
                ocrResultId,
                "CREATE",
                "ocr_status",
                previousOcrStatus,
                request.getStatus() + " (v" + nextOcrVersion + ")",
                request.getProcessedBy(),
                "SYSTEM",
                request.getErrorMessage() != null ? request.getErrorMessage() : "OCR result submitted by " + request.getEngineName()
        );

        emitOutboxEvent(
                "EVIDENCE",
                evidenceId,
                "COMPLETED".equals(request.getStatus()) ? "OCR_COMPLETED" : "OCR_FAILED",
                Map.of(
                        "evidenceId", evidenceId,
                        "ocrResultId", ocrResultId,
                        "dossierId", evidence.getDossierId(),
                        "ocrVersion", nextOcrVersion,
                        "status", request.getStatus()
                )
        );

        return toOcrResponse(savedOcr);
    }

    @Override
    public List<EvidenceOcrResultResponse> getOcrResultsByEvidenceId(String evidenceId) {
        if (!evidenceRecordRepository.existsById(evidenceId)) {
            throw new ResourceNotFoundException("Evidence not found: " + evidenceId);
        }
        return ocrResultRepository.findByEvidenceIdOrderByOcrVersionDesc(evidenceId)
                .stream()
                .map(this::toOcrResponse)
                .toList();
    }

    @Override
    public EvidenceOcrResultResponse getLatestOcrResult(String evidenceId) {
        if (!evidenceRecordRepository.existsById(evidenceId)) {
            throw new ResourceNotFoundException("Evidence not found: " + evidenceId);
        }
        return ocrResultRepository.findFirstByEvidenceIdOrderByOcrVersionDesc(evidenceId)
                .map(this::toOcrResponse)
                .orElseThrow(() -> new ResourceNotFoundException("No OCR result found for evidence: " + evidenceId));
    }

    private void validateJson(String json, String fieldName) {
        try {
            objectMapper.readTree(json);
        } catch (JsonProcessingException ex) {
            throw new BusinessValidationException("Invalid JSON format for " + fieldName);
        }
    }

    private void recordAudit(
            String dossierId,
            String entityName,
            String entityId,
            String action,
            String fieldName,
            String oldValue,
            String newValue,
            String actorId,
            String actorRole,
            String reason) {
        AuditLog log = AuditLog.builder()
                .id(UUID.randomUUID().toString())
                .dossierId(dossierId)
                .entityName(entityName)
                .entityId(entityId)
                .action(action)
                .fieldName(fieldName)
                .oldValue(oldValue)
                .newValue(newValue)
                .actorId(actorId)
                .actorRole(actorRole)
                .reason(reason)
                .build();
        auditLogRepository.save(log);
    }

    private void emitOutboxEvent(
            String aggregateType,
            String aggregateId,
            String eventType,
            Map<String, Object> payloadData) {
        try {
            String payloadJson = objectMapper.writeValueAsString(payloadData);
            OutboxEvent event = OutboxEvent.builder()
                    .id(UUID.randomUUID().toString())
                    .aggregateType(aggregateType)
                    .aggregateId(aggregateId)
                    .eventType(eventType)
                    .payload(payloadJson)
                    .status("PENDING")
                    .build();
            outboxEventRepository.save(event);
        } catch (JsonProcessingException ex) {
            throw new BusinessValidationException("Failed to serialize outbox payload");
        }
    }

    private EvidenceRecordResponse toEvidenceResponse(EvidenceRecord e) {
        return EvidenceRecordResponse.builder()
                .id(e.getId())
                .dossierId(e.getDossierId())
                .fileName(e.getFileName())
                .fileHash(e.getFileHash())
                .fileType(e.getFileType())
                .storagePath(e.getStoragePath())
                .status(e.getStatus())
                .uploadedBy(e.getUploadedBy())
                .fileSizeBytes(e.getFileSizeBytes())
                .mimeType(e.getMimeType())
                .ocrStatus(e.getOcrStatus())
                .ocrProcessedAt(e.getOcrProcessedAt())
                .version(e.getVersion())
                .isLatest(e.getIsLatest())
                .updatedBy(e.getUpdatedBy())
                .createdAt(e.getCreatedAt())
                .updatedAt(e.getUpdatedAt())
                .build();
    }

    private EvidenceOcrResultResponse toOcrResponse(EvidenceOcrResult o) {
        return EvidenceOcrResultResponse.builder()
                .id(o.getId())
                .evidenceId(o.getEvidenceId())
                .dossierId(o.getDossierId())
                .ocrVersion(o.getOcrVersion())
                .engineName(o.getEngineName())
                .engineVersion(o.getEngineVersion())
                .confidenceScore(o.getConfidenceScore())
                .rawPayload(o.getRawPayload())
                .extractedSummary(o.getExtractedSummary())
                .status(o.getStatus())
                .errorMessage(o.getErrorMessage())
                .processedBy(o.getProcessedBy())
                .processedAt(o.getProcessedAt())
                .createdAt(o.getCreatedAt())
                .build();
    }
}
