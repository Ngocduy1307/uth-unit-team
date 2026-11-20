package vn.unit.affordability.statement.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class TransactionRecordResponse {

    private String id;
    private String accountId;
    private String dossierId;
    private LocalDate transactionDate;
    private LocalDate bookingDate;
    private BigDecimal amount;
    private String currency;
    private String direction;
    private BigDecimal runningBalance;
    private String description;
    private String classification;
    private BigDecimal confidenceScore;
    private Boolean isRecurringSalary;
    private Integer sourcePage;
    private Integer sourceRow;
    private Boolean isAccepted;
    private String exclusionReason;
    private BigDecimal adjustedAmount;
    private String adjustedBy;
    private OffsetDateTime adjustedAt;
    private String adjustmentReason;
    private OffsetDateTime createdAt;
}
